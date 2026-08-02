from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.api.main as api_main
from src.api.main import app, set_services
from src.contracts.analysis import AnalysisResultV1
from src.contracts.event_candidate import ExtractedEventCandidate
from src.contracts.research import AgentType, ResearchBundle, ResearchRunStatus
from src.contracts.source_document import SourceDocument
from src.forecasting.pipeline import BaselineForecastPipeline
from src.orchestration.analysis_orchestrator import AnalysisOrchestrator
from src.orchestration.factory import ResearchServices
from src.orchestration.official_data_pipeline import FakeOfficialAdapter, OfficialDataPipeline
# capture harness intentionally accepts normalized and traversed URLs
from src.orchestration.research_pipeline import ResearchPipeline
from src.research_agents.base import AgentExecution
from src.storage import AuditRepository, Database, EventRepository, PolicyRepository, SourceRepository
from src.storage.analysis_repository import (
    AnalysisResultRepository,
    ForecastRepository,
    OfficialDataRepository,
    ScenarioResultRepository,
)
from src.validation.research_validator import ResearchEventValidator
from tests.e2e.support import load_official_observations, load_store, official_requests


pytestmark = pytest.mark.e2e
REPLAY_PATH = Path("tests/fixtures/replay/controlled_abc_replay.v1.json")


class ReplayAgent:
    agent_type = AgentType.LOCAL_EVENT
    extraction_domain = "LOCAL"

    def __init__(
        self,
        payload: dict[str, object],
        source_repo: SourceRepository,
        event_repo: EventRepository,
    ):
        self.payload = payload
        self.source_repo = source_repo
        self.event_repo = event_repo

    def run(self, request) -> AgentExecution:
        documents = {
            item.source_id: item
            for item in (
                SourceDocument.model_validate(value)
                for value in self.payload["source_documents"]
            )
        }
        candidates = [
            ExtractedEventCandidate.model_validate(value).model_copy(
                update={"research_run_id": request.run_id}
            )
            for value in self.payload["event_candidates"]
        ]
        for document in documents.values():
            self.source_repo.save(document, request.run_id)
        for candidate in candidates:
            self.event_repo.save_candidate(candidate)
        recorded = self.payload.get("research_bundles") or []
        if recorded:
            bundle = ResearchBundle.model_validate(recorded[0]).model_copy(
                update={"research_run_id": request.run_id}
            )
        else:
            bundle = ResearchBundle(
                research_run_id=request.run_id,
                agent_type=self.agent_type,
                status=ResearchRunStatus.COMPLETED,
                source_document_ids=sorted(documents),
                event_candidate_ids=sorted(item.candidate_id for item in candidates),
                metadata={"provenance": self.payload["provenance"]},
            )
        return AgentExecution(bundle=bundle, documents=documents, candidates=candidates)


class FailingOfficialAdapter:
    def process(self, request_params):
        raise TimeoutError("injected provider timeout")


def _load_replay() -> dict[str, object]:
    return json.loads(REPLAY_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_run(
    runtime_dir: Path,
    run_id: str,
    *,
    include_official: bool,
    include_research: bool,
    replay: dict[str, object] | None = None,
    rejected_research: bool = False,
    failed_official: bool = False,
):
    explicit_replay = replay is not None
    replay = replay or _load_replay()
    store_ref = replay["store_fixture"]
    official_ref = replay["official_fixture"]
    assert _sha256(Path(store_ref["path"])) == store_ref["sha256"]
    assert _sha256(Path(official_ref["path"])) == official_ref["sha256"]
    store = load_store().model_copy(
        update={
            "latitude": Decimal(store_ref["coordinate_overrides"]["latitude"]),
            "longitude": Decimal(store_ref["coordinate_overrides"]["longitude"]),
        }
    )
    request_payload = dict(replay["request"])
    request_payload["run_id"] = run_id
    if not explicit_replay:
        request_payload["store_profile_snapshot_id"] = f"SNAPSHOT-{store.store_id}"
    if not include_official:
        request_payload["official_indicator_snapshot_ids"] = []
    from src.contracts.research import ResearchRequest

    request = ResearchRequest.model_validate(request_payload)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    database = Database(f"sqlite:///{(runtime_dir / 'analysis.db').as_posix()}")
    database.migrate()
    sources = SourceRepository(database)
    events = EventRepository(database)
    policies = PolicyRepository(database)
    audit = AuditRepository(database)
    replay_payload = replay
    if rejected_research:
        replay_payload = json.loads(json.dumps(replay))
        replay_payload["event_candidates"][0]["temporal"] = {
            "start_raw": "2028-08-01",
            "end_raw": "2028-09-15",
            "recurrence_raw": None,
            "operating_hours_raw": None,
        }
    agents = (
        [ReplayAgent(replay_payload, sources, events)]
        if include_research
        else []
    )
    research = ResearchPipeline(
        agents,
        ResearchEventValidator(),
        events,
        policies,
        audit,
    )
    adapters = (
        {"FAIL": FailingOfficialAdapter()}
        if failed_official
        else {"REPLAY": FakeOfficialAdapter(load_official_observations())}
    )
    official = OfficialDataPipeline(adapters, OfficialDataRepository(database))
    orchestrator = AnalysisOrchestrator(
        research_pipeline=research,
        official_pipeline=official,
        forecast_pipeline=BaselineForecastPipeline(
            ForecastRepository(database), backtest_windows=1
        ),
        result_repository=AnalysisResultRepository(database),
        scenario_repository=ScenarioResultRepository(database),
    )
    audit.create_run(request)
    requests = []
    if include_official:
        if failed_official:
            from src.contracts.official import OfficialDataRequest

            requests = [
                OfficialDataRequest(
                    provider="FAIL",
                    indicator_id="INJECTED_FAILURE",
                    required=True,
                )
            ]
        else:
            requests = official_requests()
    execution = orchestrator.run(
        store,
        request,
        requests,
        idempotency_key=f"IDEMPOTENCY-{run_id}",
    )
    services = ResearchServices(database, research, sources, events, policies, audit)
    return execution, orchestrator, services


def _numeric_payload(result: AnalysisResultV1) -> dict[str, object]:
    return {
        "monthly_revenue_forecast": [
            item.point for item in result.baseline.monthly_forecasts
        ],
        "scenarios": {
            name: {
                "cash_flows": [
                    {
                        "revenue": item.revenue_cash_krw,
                        "ingredient_cost": item.ingredient_costs_cash_krw,
                        "other_variable_cost": item.other_variable_costs_cash_krw,
                        "interest": item.interest_payment_krw,
                        "operating_cash_flow": item.net_cash_flow_krw,
                        "cumulative_cash": item.ending_cash_krw,
                    }
                    for item in scenario.monthly_cash_flows
                ],
                "operating_bep": [
                    item.operating_bep_krw for item in scenario.bep_results
                ],
                "cash_burn_date": scenario.cash_burn_result.cash_burn_date,
            }
            for name, scenario in sorted(result.scenarios.items())
        },
    }


def test_controlled_abc_replay_explains_official_and_research_deltas(tmp_path) -> None:
    run_a, _, _ = _build_run(
        tmp_path / "a", "ABC-A-STORE", include_official=False, include_research=False
    )
    run_b, _, _ = _build_run(
        tmp_path / "b", "ABC-B-OFFICIAL", include_official=True, include_research=False
    )
    run_c, orchestrator_c, services_c = _build_run(
        tmp_path / "c", "ABC-C-REPLAY", include_official=True, include_research=True
    )
    a, b, c = run_a.result, run_b.result, run_c.result

    assert a.status == b.status == c.status == "COMPLETED"
    assert a.sections["OFFICIAL_DATA"].status.value == "SKIPPED"
    assert b.sections["OFFICIAL_DATA"].status.value == "COMPLETED"
    assert c.sections["RESEARCH"].status.value == "COMPLETED"
    assert not a.traceability.official_observation_ids and not a.traceability.event_ids
    assert b.traceability.official_observation_ids and not b.traceability.event_ids
    assert c.traceability.official_observation_ids and c.traceability.event_ids

    a_base = a.scenarios["BASELINE"].monthly_cash_flows
    b_base = b.scenarios["BASELINE"].monthly_cash_flows
    c_base = c.scenarios["BASELINE"].monthly_cash_flows
    assert [item.revenue_cash_krw for item in a_base] == [
        item.revenue_cash_krw for item in b_base
    ]
    assert any(
        right.ingredient_costs_cash_krw > left.ingredient_costs_cash_krw
        for left, right in zip(a_base, b_base)
    )
    assert any(
        right.interest_payment_krw > left.interest_payment_krw
        for left, right in zip(a_base, b_base)
    )
    assert any(
        right.ending_cash_krw < left.ending_cash_krw
        for left, right in zip(a_base, b_base)
    )
    assert _numeric_payload(b)["scenarios"]["BASELINE"] == _numeric_payload(c)[
        "scenarios"
    ]["BASELINE"]

    for scenario_name in ("LOW_IMPACT", "HIGH_IMPACT"):
        b_flows = b.scenarios[scenario_name].monthly_cash_flows
        c_flows = c.scenarios[scenario_name].monthly_cash_flows
        assert any(
            right.revenue_cash_krw < left.revenue_cash_krw
            for left, right in zip(b_flows, c_flows)
        )
        assert any(
            right.net_cash_flow_krw < left.net_cash_flow_krw
            for left, right in zip(b_flows, c_flows)
        )
        assert all(
            right.interest_payment_krw == left.interest_payment_krw
            for left, right in zip(b_flows, c_flows)
        )

    assert all(
        cash_flow.variable_costs_cash_krw
        == cash_flow.ingredient_costs_cash_krw
        + cash_flow.other_variable_costs_cash_krw
        for scenario in c.scenarios.values()
        for cash_flow in scenario.monthly_cash_flows
    )
    bounds = {
        "LOW_IMPACT": (Decimal(str(math.exp(-0.10))), Decimal(str(math.exp(0.10)))),
        "HIGH_IMPACT": (Decimal(str(math.exp(-0.15))), Decimal(str(math.exp(0.15)))),
    }
    for name, (lower, upper) in bounds.items():
        assert all(
            lower <= month.revenue_multiplier <= upper
            for month in c.adjustments[name].months
        )
    accepted = c.research.accepted_events
    assert {item.event_id for item in accepted} == set(c.traceability.event_ids)
    assert all(item.cause_group_id for item in accepted)
    assert {
        impact.axis
        for event in accepted
        for impact in event.impacts
    }.isdisjoint({"INGREDIENT_COST", "INTEREST_COST"})
    assert c.versions.coefficient_version == "coefficients.v1"
    assert c.versions.official_feature_version == "official_features.v2.decayed_capped"
    assert c.versions.financial_calculation_version == "financial_calculation.v2"
    assert all(
        scenario.metadata["coefficient_version"] == "coefficients.v1"
        and set(filter(None, scenario.metadata["official_observation_ids"].split(",")))
        <= set(c.traceability.official_observation_ids)
        for scenario in c.scenarios.values()
    )

    restored = orchestrator_c.result_repository.get(c.run_id, version=1)
    assert restored and restored.deterministic_hash == c.deterministic_hash
    set_services(services_c)
    api_main._orchestrator = orchestrator_c
    try:
        client = TestClient(app)
        response = client.get(f"/v1/analyses/{c.run_id}/result", params={"version": 1})
        assert response.status_code == 200
        assert response.json()["deterministic_hash"] == c.deterministic_hash
        for event_id in c.traceability.event_ids:
            evidence = client.get(f"/v1/events/{event_id}/evidence")
            assert evidence.status_code == 200 and evidence.json()["evidence"]
        for source_id in c.traceability.source_ids:
            source = client.get(f"/v1/sources/{source_id}")
            assert source.status_code == 200, source.text
    finally:
        api_main._services = None
        api_main._orchestrator = None


def test_rejected_events_and_failed_provider_calls_have_no_hidden_numeric_effect(
    tmp_path,
) -> None:
    baseline, _, _ = _build_run(
        tmp_path / "baseline",
        "ABC-A-FAILURE-CONTROL",
        include_official=False,
        include_research=False,
    )
    failed, _, _ = _build_run(
        tmp_path / "failed",
        "ABC-A-FAILED-PROVIDER",
        include_official=True,
        include_research=False,
        failed_official=True,
    )
    accepted_official, _, _ = _build_run(
        tmp_path / "official",
        "ABC-B-REJECTION-CONTROL",
        include_official=True,
        include_research=False,
    )
    rejected, _, _ = _build_run(
        tmp_path / "rejected",
        "ABC-B-REJECTED-EVENT",
        include_official=True,
        include_research=True,
        rejected_research=True,
    )

    assert failed.result.sections["OFFICIAL_DATA"].status.value == "FAILED"
    assert failed.result.status == "PARTIAL"
    assert _numeric_payload(failed.result) == _numeric_payload(baseline.result)
    assert rejected.result.research.accepted_events == []
    assert rejected.result.research.rejected_events
    assert rejected.result.signals == []
    assert _numeric_payload(rejected.result) == _numeric_payload(
        accepted_official.result
    )


def test_replay_bundle_generation_and_ten_run_hash_are_stable(tmp_path) -> None:
    from scripts.generate_integrated_replay_bundle import build_bundle

    generated = build_bundle(Path.cwd())
    assert generated == _load_replay()
    hashes = set()
    numeric_payloads = set()
    for index in range(10):
        execution, _, _ = _build_run(
            tmp_path / str(index),
            "ABC-C-REPLAY",
            include_official=True,
            include_research=True,
        )
        hashes.add(execution.result.deterministic_hash)
        numeric_payloads.add(
            json.dumps(
                _numeric_payload(execution.result),
                default=str,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    assert len(hashes) == len(numeric_payloads) == 1


@pytest.mark.live
def test_live_integrated_analysis_saves_sanitized_replay_bundle(tmp_path) -> None:
    from src.config.credential_validation import get_credential
    from src.config.settings import Settings
    from src.contracts.research import ReasoningLevel
    from src.providers.base import SearchProviderError, SearchRequest
    from src.providers.search.gemini import GeminiSearchProvider

    if not get_credential("GEMINI_API_KEY"):
        pytest.skip("Gemini credential is not configured")
    if not get_credential("OPENAI_API_KEY"):
        pytest.skip("OpenAI credential is not configured")
    settings = Settings()
    discoveries = []
    def live_search(search_request):
        try:
            return GeminiSearchProvider(settings).search(search_request)
        except SearchProviderError as exc:
            if exc.code == "TIMEOUT":
                return None
            raise

    for attempt in range(settings.max_search_retries + 1):
        result = live_search(
            SearchRequest(
                query="site:bok.or.kr 2026년 7월 통화정책방향 기준금리 결정 보도자료",
                domain="MACRO",
                reasoning_level=ReasoningLevel.LOW,
                max_results=3,
                allowed_domains=["bok.or.kr"],
                request_id=f"LIVE-INTEGRATED-DISCOVERY-{attempt + 1}",
            )
        )
        if result is None:
            continue
        if result.raw_metadata["grounding_present"] and result.hits:
            discoveries.append(result)
            break
    assert discoveries, "Gemini produced no grounded URLs for live capture"

    from src.contracts.source_document import AccessStatus
    from src.normalization.geo_normalizer import MapApiGeocoder
    from src.providers.extraction.openai import OpenAIEventExtractor
    from src.research_agents.macro.agent import MacroResearchAgent
    from src.source_snapshot.fetcher import HttpDocumentFetcher

    fetched = [
        (bundle, hit, HttpDocumentFetcher(settings).fetch(hit))
        for bundle in discoveries
        for hit in bundle.hits
    ]
    usable = [
        (bundle, hit, document)
        for bundle, hit, document in fetched
        if document.access_status == AccessStatus.OK
    ]
    assert usable, "No grounded BOK document passed fetch security checks"
    selected_bundle, selected_hit, selected_document = max(
        usable,
        key=lambda item: len(item[2].body_text),
    )
    metadata = {
        **selected_bundle.raw_metadata,
        "capture_search_attempt_count": settings.max_search_retries + 1,
    }
    discovery = selected_bundle.model_copy(
        update={"hits": [selected_hit], "raw_metadata": metadata}
    )

    class CapturedSearchProvider:
        def search(self, request):
            return discovery.model_copy(update={"request_id": request.request_id})

    class CapturedDocumentFetcher:
        def fetch(self, hit):
            _ = hit
            return selected_document

    class SingleQueryMacroAgent(MacroResearchAgent):
        def build_queries(self, request):
            return ["site:bok.or.kr 2026년 7월 통화정책방향 기준금리 결정 보도자료"]

    replay = _load_replay()
    run_id = "LIVE-INTEGRATED-CAPTURE"
    runtime = tmp_path / "live"
    runtime.mkdir()
    database = Database(f"sqlite:///{(runtime / 'analysis.db').as_posix()}")
    database.migrate()
    sources = SourceRepository(database)
    events = EventRepository(database)
    policies = PolicyRepository(database)
    audit = AuditRepository(database)
    agent = SingleQueryMacroAgent(
        search=CapturedSearchProvider(),
        fetcher=CapturedDocumentFetcher(),
        extractor=OpenAIEventExtractor(settings),
        source_repo=sources,
        event_repo=events,
        audit_repo=audit,
    )
    research = ResearchPipeline(
        [agent],
        ResearchEventValidator(geocoder=MapApiGeocoder()),
        events,
        policies,
        audit,
    )
    official = OfficialDataPipeline(
        {"REPLAY": FakeOfficialAdapter(load_official_observations())},
        OfficialDataRepository(database),
    )
    orchestrator = AnalysisOrchestrator(
        research_pipeline=research,
        official_pipeline=official,
        forecast_pipeline=BaselineForecastPipeline(
            ForecastRepository(database), backtest_windows=1
        ),
        result_repository=AnalysisResultRepository(database),
        scenario_repository=ScenarioResultRepository(database),
    )
    store = load_store().model_copy(
        update={"latitude": Decimal("37.5007"), "longitude": Decimal("127.0365")}
    )
    request_payload = dict(replay["request"])
    request_payload["run_id"] = run_id
    from src.contracts.research import ResearchRequest

    request = ResearchRequest.model_validate(request_payload)
    audit.create_run(request)
    execution = orchestrator.run(
        store,
        request,
        official_requests(),
        idempotency_key="IDEMPOTENCY-LIVE-INTEGRATED-CAPTURE",
    )
    assert execution.research.errors == []
    assert execution.research.bundles
    assert execution.research.documents
    live_diagnostics = execution.research.bundles[0].diagnostics
    assert live_diagnostics.fetched_document_count > 0
    assert all(
        failure.error_code not in {
            "AGENT_WALL_CLOCK_DEADLINE_EXHAUSTED",
            "AGENT_WALL_CLOCK_RESERVE_REACHED",
        }
        for failure in execution.research.bundles[0].provider_failures
    )
    assert len(execution.result.deterministic_hash) == 64
    assert execution.result.status in {"COMPLETED", "PARTIAL"}
    assert live_diagnostics.configured_limits["agent_wall_clock_limit_seconds"] is None

    from sqlalchemy import select
    from src.storage.schema import event_candidates

    with database.engine.connect() as connection:
        candidate_payloads = list(
            connection.execute(select(event_candidates.c.candidate_json)).scalars()
        )
    live_bundle = {
        **replay,
        "provenance": "LIVE_CAPTURE",
        "capture_status": "COMPLETED",
        "run_id": run_id,
        "request": request.model_dump(mode="json"),
        "source_documents": [
            item.model_dump(mode="json")
            for item in execution.research.documents.values()
        ],
        "event_candidates": candidate_payloads,
        "accepted_events": [
            item.model_dump(mode="json")
            for item in execution.research.accepted_events
        ],
        "research_bundles": [
            item.model_dump(mode="json") for item in execution.research.bundles
        ],
        "limitations": (
            [] if execution.research.accepted_events
            else ["NO_EVENT_PASSED_DETERMINISTIC_VALIDATION"]
        ),
    }
    output = tmp_path / "live_integrated_replay.sanitized.json"
    serialized = json.dumps(
        live_bundle, ensure_ascii=False, indent=2, sort_keys=True
    )
    assert "api_key" not in serialized.lower()
    assert "authorization" not in serialized.lower()
    output.write_text(serialized + "\n", encoding="utf-8")

    replayed, _, _ = _build_run(
        tmp_path / "live-replay",
        run_id,
        include_official=True,
        include_research=True,
        replay=live_bundle,
    )
    assert _numeric_payload(replayed.result) == _numeric_payload(execution.result)
    if execution.research.accepted_events:
        assert replayed.result.deterministic_hash == execution.result.deterministic_hash
    else:
        # No-event live captures still require deterministic numeric replay.
        assert len(replayed.result.deterministic_hash) == 64
    assert output.exists()
