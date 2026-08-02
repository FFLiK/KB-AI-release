from datetime import UTC, date, datetime
from decimal import Decimal

from src.contracts.analysis import TraceabilityManifest
from src.contracts.forecast import BaselineForecastBundle, ForecastStatus, IntervalKind, MonthlyForecast
from src.contracts.loan import Loan
from src.contracts.official import OfficialDataRequest
from src.contracts.policy_candidate import EligibilityCondition
from src.contracts.scenario import MonthlyScenarioAdjustment, ScenarioAdjustmentV2
from src.contracts.store import (
    FixedCostScheduleEntry,
    MonthlyFixedCostDetail,
    MonthlyHistory,
    StoreProfile,
)
from src.finance.loan import calculate_loan_schedule
from src.finance.monthly_scenario import run_monthly_financial_scenario
from src.orchestration.official_data_pipeline import FakeOfficialAdapter, OfficialDataPipeline
from src.relief.eligibility_rules import evaluate_policy_eligibility_detailed
from src.relief.policy_schema import PolicySchema
from src.reporting.grounded_summary import build_grounded_summary
from src.storage import AnalysisJobRepository, Database, OfficialDataRepository


def _store(**updates):
    values = {
        "store_id": "STORE-STRUCT",
        "address": "Seoul",
        "minimum_operating_cash_krw": Decimal("100"),
        "current_cash_krw": Decimal("1000"),
        "monthly_history": [MonthlyHistory(
            month="2026-06",
            revenue_krw=Decimal("1000"),
            fixed_costs=MonthlyFixedCostDetail(
                rent_krw=Decimal("100"),
                labor_krw=Decimal("100"),
                utilities_krw=Decimal("100"),
                other_krw=Decimal("100"),
            ),
        )],
    }
    values.update(updates)
    return StoreProfile(**values)


def _baseline():
    return BaselineForecastBundle(
        forecast_id="FC-STRUCT",
        status=ForecastStatus.COMPLETED,
        selected_model="RECENT_MEAN",
        model_version="1",
        available_months=1,
        monthly_forecasts=[MonthlyForecast(
            month="2026-07",
            point=Decimal("1000"),
            lower=Decimal("900"),
            upper=Decimal("1100"),
        )],
        interval_kind=IntervalKind.ASSUMPTION_RANGE,
    )


def _adjustment():
    return ScenarioAdjustmentV2(
        adjustment_id="ADJ-STRUCT",
        scenario="BASELINE",
        months=[MonthlyScenarioAdjustment(month="2026-07")],
    )


def test_fixed_cost_schedule_overrides_only_declared_category():
    store = _store(fixed_cost_schedule=[
        FixedCostScheduleEntry(month="2026-07", category="rent", amount_krw=Decimal("250"))
    ])
    result = run_monthly_financial_scenario(store, _baseline(), _adjustment())
    assert result.monthly_cash_flows[0].fixed_costs_cash_krw == Decimal("550")


def test_loan_schedule_respects_next_payment_and_grace_dates():
    loan = Loan(
        loan_id="LOAN-DATES",
        principal_balance_krw=Decimal("1200"),
        annual_interest_rate=Decimal("0.12"),
        repayment_type="EQUAL_PRINCIPAL",
        remaining_months=12,
        next_payment_date="2026-08-15",
        grace_end_date="2026-09-30",
    )
    schedule, _ = calculate_loan_schedule(loan, 4, forecast_start=date(2026, 7, 1))
    assert schedule[0].principal_payment_krw == 0
    assert schedule[0].interest_payment_krw == 0
    assert schedule[1].principal_payment_krw == 0
    assert schedule[1].interest_payment_krw > 0
    assert schedule[3].principal_payment_krw > 0


def test_policy_conditions_fail_closed_for_missing_data_and_log_results():
    policy = PolicySchema(
        policy_id="POL-1",
        name="Policy",
        provider="Provider",
        budget_status="AVAILABLE",
        eligibility_conditions=[
            EligibilityCondition(field_path="annual_revenue_krw", operator="LE", expected_value=5000)
        ],
    )
    status, reason, logs = evaluate_policy_eligibility_detailed(
        _store(), policy, "11", date(2026, 7, 1)
    )
    assert status == "NEEDS_INFORMATION"
    assert "annual_revenue_krw" in reason
    assert logs[0]["status"] == "NEEDS_INFORMATION"

    status, _, logs = evaluate_policy_eligibility_detailed(
        _store(annual_revenue_krw=Decimal("4000")), policy, "11", date(2026, 7, 1)
    )
    assert status == "ELIGIBLE_ON_DECLARED_RULES"
    assert logs[0]["status"] == "PASSED"


def test_official_pipeline_persists_vintage_but_rejects_missing_release(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'official.db').as_posix()}")
    db.migrate()
    pipeline = OfficialDataPipeline(
        {"FAKE": FakeOfficialAdapter([{
            "indicator_id": "RATE",
            "value": "3.5",
            "unit": "PERCENT",
            "frequency": "MONTHLY",
            "observed_at": "2026-06-01",
            "source_id": "SRC-RATE",
        }])},
        OfficialDataRepository(db),
    )
    bundle = pipeline.run(
        "RUN-OFFICIAL-FAIL-CLOSED",
        date(2026, 7, 1),
        [OfficialDataRequest(provider="FAKE", indicator_id="RATE", required=True)],
    )
    assert not bundle.observations
    assert bundle.source_vintages[0].revision_basis == "CONTENT_HASH"
    assert "MISSING_RELEASE_METADATA" in bundle.provider_errors["FAKE:0"]


def test_grounded_summary_rejects_unknown_citations_and_job_error_is_durable(tmp_path):
    scenario = run_monthly_financial_scenario(_store(), _baseline(), _adjustment())
    trace = TraceabilityManifest(
        model_run_ids=["FC-STRUCT"],
        scenario_ids=[scenario.metadata["scenario_id"]],
        calculation_result_ids=[scenario.metadata["scenario_id"]],
    )
    summary = build_grounded_summary("AR-1", _baseline(), {"BASELINE": scenario}, trace)
    assert summary.validation_status == "VALIDATED"
    assert all(statement.citation_ids for statement in summary.statements)

    db_url = f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"
    db = Database(db_url)
    db.migrate()
    repo = AnalysisJobRepository(db)
    repo.create("RUN-JOB", "abc")
    repo.update("RUN-JOB", "FAILED", {"type": "ValueError", "message": "bad"})
    reopened = AnalysisJobRepository(Database(db_url)).get("RUN-JOB")
    assert reopened["status"] == "FAILED"
    assert reopened["error_json"]["type"] == "ValueError"
