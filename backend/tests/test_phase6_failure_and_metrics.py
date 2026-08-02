from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import event, select

from src.contracts.official import OfficialDataRequest
from src.contracts.research import AgentType, ResearchBundle, ResearchRunStatus
from src.operations.metrics import metrics
from src.orchestration.official_data_pipeline import FakeOfficialAdapter, OfficialDataPipeline
from src.orchestration.research_pipeline import ResearchPipeline
from src.research_agents.base import AgentExecution
from src.storage import AuditRepository, Database, EventRepository, PolicyRepository
from src.storage.analysis_repository import OfficialDataRepository
from src.storage.schema import analysis_results, analysis_sections, official_data_vintages
from src.validation.research_validator import ResearchEventValidator
from tests.e2e.support import (
    build_orchestrator,
    load_official_observations,
    load_store,
    official_requests,
    research_request,
)
from tests.research_fixtures import candidate, research_request as fixture_request, source_document


def test_changed_official_field_fails_closed_and_duplicate_revision_is_idempotent(
    tmp_path,
) -> None:
    metrics.reset()
    database = Database(f"sqlite:///{(tmp_path / 'official-failures.db').as_posix()}")
    database.migrate()
    repository = OfficialDataRepository(database)
    changed_field = {
        "indicator_id": "USD_KRW",
        "value": "1326",
        "unit": "KRW_PER_USD",
        "observation_date": "2026-06-01",
        "released_at": "2026-07-10T09:00:00+09:00",
        "available_at": "2026-07-11T09:00:00+09:00",
        "source_id": "SRC-CHANGED-FIELD",
        "source_revision_id": "REV-CHANGED-FIELD",
    }
    failed = OfficialDataPipeline(
        {"REPLAY": FakeOfficialAdapter([changed_field])}, repository
    ).run(
        "FAIL-CHANGED-FIELD",
        date(2026, 7, 31),
        [
            OfficialDataRequest(
                provider="REPLAY",
                indicator_id="USD_KRW",
                required=True,
            )
        ],
    )
    assert failed.status == "FAILED"
    assert failed.observations == []
    assert any(
        "INVALID_OBSERVATION" in value for value in failed.provider_errors.values()
    )

    replay = OfficialDataPipeline(
        {"REPLAY": FakeOfficialAdapter(load_official_observations())}, repository
    )
    for run_id in ("DUPLICATE-REVISION-1", "DUPLICATE-REVISION-2"):
        bundle = replay.run(
            run_id,
            date(2026, 7, 31),
            [
                OfficialDataRequest(
                    provider="REPLAY",
                    indicator_id="USD_KRW",
                    required=True,
                )
            ],
        )
        assert len(bundle.observations) == 2
    with database.engine.connect() as connection:
        vintages = connection.execute(
            select(official_data_vintages.c.vintage_id)
        ).scalars().all()
    assert len(vintages) == len(set(vintages)) == 2
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["official_records_rejected_total"] == 1
    assert snapshot["counters"]["official_records_accepted_total"] == 4


def test_analysis_result_transaction_rolls_back_on_database_write_interruption(
    tmp_path,
) -> None:
    orchestrator, database = build_orchestrator(tmp_path)
    store = load_store()
    request = research_request(store, run_id="DB-WRITE-INTERRUPTION")

    def interrupt_sections(_conn, _cursor, statement, _parameters, _context, _many):
        if "INSERT INTO analysis_sections" in statement:
            raise RuntimeError("injected database write interruption")

    event.listen(database.engine, "before_cursor_execute", interrupt_sections)
    try:
        with pytest.raises(RuntimeError, match="injected database write interruption"):
            orchestrator.run(
                store,
                request,
                official_requests(),
                idempotency_key="DB-WRITE-INTERRUPTION",
            )
    finally:
        event.remove(database.engine, "before_cursor_execute", interrupt_sections)

    with database.engine.connect() as connection:
        assert connection.execute(select(analysis_results)).all() == []
        assert connection.execute(select(analysis_sections)).all() == []


class RejectedReplayAgent:
    agent_type = AgentType.LOCAL_EVENT
    extraction_domain = "LOCAL"

    def __init__(self):
        self.document = source_document()
        self.candidate = candidate(
            self.document,
            start="2028-08-01",
            end="2028-09-15",
        )

    def run(self, request) -> AgentExecution:
        item = self.candidate.model_copy(update={"research_run_id": request.run_id})
        return AgentExecution(
            bundle=ResearchBundle(
                research_run_id=request.run_id,
                agent_type=self.agent_type,
                status=ResearchRunStatus.COMPLETED,
                source_document_ids=[self.document.source_id],
                event_candidate_ids=[item.candidate_id],
            ),
            documents={self.document.source_id: self.document},
            candidates=[item],
        )


def test_operational_metrics_cover_provider_research_scenario_and_replay(tmp_path) -> None:
    metrics.reset()
    orchestrator, _ = build_orchestrator(tmp_path / "analysis")
    store = load_store()
    request = research_request(store, run_id="METRICS-ANALYSIS")
    execution = orchestrator.run(
        store,
        request,
        official_requests(),
        idempotency_key="METRICS-ANALYSIS",
    )
    metrics.record_replay_comparison(
        execution.result.deterministic_hash,
        execution.result.deterministic_hash,
    )
    metrics.record_replay_comparison(execution.result.deterministic_hash, "mismatch")

    database = Database(f"sqlite:///{(tmp_path / 'research.db').as_posix()}")
    database.migrate()
    events = EventRepository(database)
    policies = PolicyRepository(database)
    audit = AuditRepository(database)
    rejected_pipeline = ResearchPipeline(
        [RejectedReplayAgent()],
        ResearchEventValidator(),
        events,
        policies,
        audit,
    )
    rejected_result = rejected_pipeline.run(fixture_request("METRICS-REJECTED"))
    assert rejected_result.accepted_events == []
    assert rejected_result.rejected_events

    snapshot = metrics.snapshot()
    counters = snapshot["counters"]
    distributions = snapshot["distributions"]
    assert counters["analysis_completed_total"] == 1
    assert counters["official_provider_requests_total"] == 4
    assert counters["official_records_fetched_total"] == 8
    assert counters["official_records_accepted_total"] == 8
    assert counters["event_rejected_total"] == 1
    assert counters["validation_failure_forecast_window_not_overlapped_total"] == 1
    assert counters["deterministic_replay_comparison_total"] == 2
    assert counters["deterministic_replay_mismatch_total"] == 1
    assert distributions["official_provider_latency_ms"]["count"] == 4
    assert distributions["official_freshness_age_days"]["count"] == 4
    assert distributions["scenario_calculation_latency_ms"]["count"] == 3
    assert snapshot["gauges"]["event_acceptance_ratio"] == 0
