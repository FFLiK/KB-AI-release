from datetime import date

import pytest

from src.forecasting.pipeline import BaselineForecastPipeline
from src.signals.monthly_builder import MonthlySignalBuilder
from src.validation.research_validator import ResearchEventValidator
from tests.e2e.support import (
    build_orchestrator,
    load_store,
    official_requests,
    research_request,
)
from tests.research_fixtures import candidate, source_document


pytestmark = pytest.mark.e2e


def test_offline_analysis_runs_all_deterministic_sections_and_recovers_result(tmp_path) -> None:
    store = load_store()
    request = research_request(store)
    orchestrator, database = build_orchestrator(tmp_path)

    execution = orchestrator.run(
        store,
        request,
        official_requests(),
        idempotency_key="OFFLINE-E2E-IDEMPOTENCY-V1",
    )
    result = execution.result

    assert result.status == "COMPLETED"
    assert len(result.official_data.observations) == 8
    assert len(result.trend_baseline.monthly_forecasts) == 6
    assert result.trend_scenario is not None
    assert len(result.baseline.monthly_forecasts) == 6
    assert result.trend_scenario.metadata["official_observation_ids"] == ""
    assert result.scenarios["BASELINE"].metadata["official_observation_ids"]
    assert (
        result.scenarios["BASELINE"].monthly_cash_flows[0].variable_costs_cash_krw
        > result.trend_scenario.monthly_cash_flows[0].variable_costs_cash_krw
    )
    assert len(result.traceability.model_run_ids) == 2
    assert set(result.scenarios) == {"BASELINE", "LOW_IMPACT", "HIGH_IMPACT"}
    assert execution.report is not None
    assert execution.report.baseline_scenario == result.scenarios["BASELINE"]

    restored = orchestrator.result_repository.get(request.run_id)
    assert restored is not None
    assert restored.deterministic_hash == result.deterministic_hash
    assert restored.model_dump(mode="json") == result.model_dump(mode="json")

    persisted_official_ids = set(result.traceability.official_observation_ids)
    assert persisted_official_ids == {item.observation_id for item in result.official_data.observations}
    assert result.traceability.source_ids == sorted({item.source_id for item in result.official_data.observations})
    for scenario in execution.report.model_dump(mode="json").values():
        if not isinstance(scenario, dict) or "metadata" not in scenario:
            continue
        reported_ids = set(filter(None, scenario["metadata"]["official_observation_ids"].split(",")))
        assert reported_ids <= persisted_official_ids

    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("select count(*) from official_observations").scalar_one() == 8
        assert connection.exec_driver_sql("select count(*) from analysis_results").scalar_one() == 1


def test_rejected_event_and_invalid_geography_have_zero_scenario_effect() -> None:
    store = load_store("invalid_address_store.json")
    document = source_document()
    rejected_candidate = candidate(document, start="2027-08-01", end="2027-09-15")
    rejected_candidate.location.latitude = None
    rejected_candidate.location.longitude = None
    request = research_request(store, run_id="OFFLINE-REJECTED-EVENT")

    outcome = ResearchEventValidator().validate(
        rejected_candidate,
        {document.source_id: document},
        request,
    )

    assert outcome.status == "REJECTED"
    assert "FORECAST_WINDOW_NOT_OVERLAPPED" in outcome.failure_codes
    assert "GEO_PROVIDER_NOT_CONFIGURED" not in outcome.failure_codes
    assert "GEO_NOT_FOUND" not in outcome.failure_codes
    signals, adjustments = MonthlySignalBuilder().build([], store, request.forecast_start, 6)
    assert signals == []
    assert all(
        month.revenue_multiplier == 1
        and month.variable_cost_multiplier == 1
        and not month.event_ids
        for adjustment in adjustments.values()
        for month in adjustment.months
    )


def test_three_month_store_uses_explicit_fallback_without_long_history() -> None:
    store = load_store("new_store_3m.json")
    bundle = BaselineForecastPipeline().run(
        "OFFLINE-NEW-STORE",
        store,
        date(2026, 8, 1),
    )

    assert bundle.status == "PARTIAL"
    assert bundle.selected_model == "LAST_OBSERVED_ASSUMPTION"
    assert bundle.available_months == 3
    assert bundle.fallback_reason == "Only 3 historical months are available"
    assert all(item.is_assumption_range for item in bundle.monthly_forecasts)
