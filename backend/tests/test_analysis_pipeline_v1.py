from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from src.api.main import app, set_services
from src.contracts.forecast import BaselineForecastBundle, ForecastStatus, IntervalKind, MonthlyForecast
from src.contracts.official import OfficialDataRequest
from src.contracts.scenario import MonthlyScenarioAdjustment, ScenarioAdjustmentV2
from src.contracts.store import MonthlyCostDetail, MonthlyFixedCostDetail, MonthlyHistory, StoreProfile
from src.finance.monthly_scenario import run_monthly_financial_scenario
from src.forecasting.official_features import OfficialFeatureBuilder
from src.forecasting.pipeline import BaselineForecastPipeline
from src.orchestration.official_data_pipeline import FakeOfficialAdapter, OfficialDataPipeline
from src.storage import Database
from src.storage.analysis_repository import OfficialDataRepository
from tests.research_fixtures import research_request
from tests.test_research_integration import services_for, store


def _history(months: int) -> list[MonthlyHistory]:
    output = []
    for index in range(months):
        year = 2025 + index // 12
        month = index % 12 + 1
        output.append(MonthlyHistory(
            month=f"{year:04d}-{month:02d}",
            revenue_krw=Decimal("10000000") + Decimal(index) * Decimal("1000000"),
        ))
    return output


def test_backtested_forecast_selects_real_trend_model():
    profile = StoreProfile(
        store_id="TREND", address="Seoul", minimum_operating_cash_krw=Decimal("0"),
        current_cash_krw=Decimal("0"), forecast_horizon_months=3, monthly_history=_history(8),
    )
    bundle = BaselineForecastPipeline().run("RUN-TREND", profile, date(2025, 9, 1))
    assert bundle.selected_model == "RECENT_TREND"
    assert {metric.model_name for metric in bundle.candidate_metrics} == {"RECENT_MEAN", "RECENT_TREND"}
    assert bundle.monthly_forecasts[1].point > bundle.monthly_forecasts[0].point


def test_forecast_without_history_does_not_invent_revenue():
    profile = StoreProfile(
        store_id="EMPTY", address="Seoul", minimum_operating_cash_krw=Decimal("0"),
        current_cash_krw=Decimal("0"), forecast_horizon_months=3,
    )
    bundle = BaselineForecastPipeline().run("RUN-EMPTY", profile, date(2026, 8, 1))
    assert bundle.status == ForecastStatus.INSUFFICIENT_DATA
    assert bundle.monthly_forecasts == []


def test_official_pipeline_persists_vintage_and_rejects_future(tmp_path):
    db = Database(f"sqlite:///{(tmp_path/'official.db').as_posix()}")
    db.migrate()
    adapter = FakeOfficialAdapter([
        {
            "indicator_id": "BASE_RATE", "value": "3.5", "unit": "PERCENT",
            "frequency": "MONTHLY", "observed_at": "2026-07-01",
            "released_at": "2026-07-02T09:00:00+09:00", "source_id": "SRC-ECOS",
            "source_revision_id": "REV-1",
        },
        {
            "indicator_id": "BASE_RATE", "value": "9.9", "unit": "PERCENT",
            "frequency": "MONTHLY", "observed_at": "2026-09-01",
            "released_at": "2026-09-02T09:00:00+09:00", "source_id": "SRC-ECOS",
            "source_revision_id": "REV-1",
        },
    ])
    pipeline = OfficialDataPipeline({"ECOS": adapter}, OfficialDataRepository(db))
    bundle = pipeline.run("RUN-OFFICIAL", date(2026, 7, 31), [
        OfficialDataRequest(provider="ECOS", indicator_id="BASE_RATE", required=True, max_age_days=60)
    ])
    assert [item.value for item in bundle.observations] == [Decimal("3.5")]
    assert bundle.source_vintages[0].source_revision_id == "REV-1"
    with db.engine.connect() as conn:
        assert conn.exec_driver_sql("select count(*) from official_observations").scalar_one() == 1


def test_registered_cpi_changes_domestic_cost_without_becoming_revenue_demand():
    records = [
        {
            "indicator_id": "CONSUMER_PRICE_INDEX", "value": value, "unit": "INDEX_2020_100",
            "frequency": "MONTHLY", "observed_at": observed_at,
            "released_at": released_at, "source_id": "SRC-KOSIS-CPI",
            "source_revision_id": f"REV-{observed_at}",
        }
        for value, observed_at, released_at in (
            ("100", "2026-05-01", "2026-06-02T09:00:00+09:00"),
            ("105", "2026-06-01", "2026-07-02T09:00:00+09:00"),
        )
    ]
    bundle = OfficialDataPipeline({"KOSIS": FakeOfficialAdapter(records)}).run(
        "RUN-CPI-ROLE",
        date(2026, 7, 31),
        [OfficialDataRequest(provider="KOSIS", indicator_id="CONSUMER_PRICE_INDEX")],
    )
    month = OfficialFeatureBuilder().build(bundle, date(2026, 8, 1), 1).months[0]
    assert month.revenue_index_multiplier == Decimal("1")
    assert month.domestic_ingredient_cost_multiplier == Decimal("1.05")
    assert month.imported_ingredient_cost_multiplier == Decimal("1")


def test_monthly_finance_uses_each_forecast_and_adjustment_month():
    profile = store()
    baseline = BaselineForecastBundle(
        forecast_id="FRC-MONTHLY", status=ForecastStatus.COMPLETED,
        selected_model="RECENT_TREND", model_version="recent_trend.v1", available_months=8,
        interval_kind=IntervalKind.PREDICTION_INTERVAL,
        monthly_forecasts=[
            MonthlyForecast(month="2026-08", point=Decimal("30000000"), lower=Decimal("28000000"), upper=Decimal("32000000")),
            MonthlyForecast(month="2026-09", point=Decimal("40000000"), lower=Decimal("38000000"), upper=Decimal("42000000")),
        ],
    )
    adjustment = ScenarioAdjustmentV2(
        adjustment_id="ADJ-MONTHLY", scenario="HIGH_IMPACT",
        months=[
            MonthlyScenarioAdjustment(month="2026-08"),
            MonthlyScenarioAdjustment(month="2026-09", revenue_multiplier=Decimal("0.5")),
        ],
    )
    result = run_monthly_financial_scenario(profile, baseline, adjustment)
    assert result.monthly_cash_flows[0].revenue_cash_krw == Decimal("30000000")
    assert result.monthly_cash_flows[1].revenue_cash_krw == Decimal("20000000")
    assert result.metadata["forecast_id"] == baseline.forecast_id


def test_versioned_api_persists_and_recovers_result(tmp_path):
    run_id = "RES-V1-API"
    svc = services_for(tmp_path, run_id=run_id)
    set_services(svc)
    client = TestClient(app)
    payload = {
        "store_profile": store().model_dump(mode="json"),
        "research_request": research_request(run_id).model_dump(mode="json"),
        "official_data_requests": [],
    }
    first = client.post("/v1/analyses/sync", json=payload, headers={"Idempotency-Key": "IDEM-V1"})
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["schema_version"] == "analysis_result.v1"
    assert result["deterministic_hash"]
    assert result["sections"]["RESULT_ASSEMBLY"]["status"] == "COMPLETED"
    assert result["scenarios"]["HIGH_IMPACT"]["metadata"]["forecast_id"] == result["baseline"]["forecast_id"]

    set_services(svc)
    restored = TestClient(app).get(f"/v1/analyses/{run_id}/result")
    assert restored.status_code == 200
    assert restored.json()["deterministic_hash"] == result["deterministic_hash"]

    repeated = TestClient(app).post(
        "/v1/analyses/sync", json=payload, headers={"Idempotency-Key": "IDEM-V1"}
    )
    assert repeated.status_code == 200
    assert repeated.json()["result_id"] == result["result_id"]


def test_what_if_is_tied_to_persisted_base_result(tmp_path):
    run_id = "RES-WHATIF"
    svc = services_for(tmp_path, run_id=run_id)
    set_services(svc)
    client = TestClient(app)
    payload = {
        "store_profile": store().model_dump(mode="json"),
        "research_request": research_request(run_id).model_dump(mode="json"),
    }
    created = client.post("/v1/analyses/sync", json=payload)
    assert created.status_code == 200
    what_if = client.post(f"/v1/analyses/{run_id}/what-if", json={"revenue_multiplier": "0.5"})
    assert what_if.status_code == 200, what_if.text
    assert what_if.json()["base_result_id"] == created.json()["result_id"]
    baseline_revenue = created.json()["baseline"]["monthly_forecasts"][0]["point"]
    what_if_revenue = what_if.json()["scenario"]["monthly_cash_flows"][0]["revenue_cash_krw"]
    assert Decimal(what_if_revenue) == Decimal(baseline_revenue) * Decimal("0.5")
