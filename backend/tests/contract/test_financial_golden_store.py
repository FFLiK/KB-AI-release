from datetime import date
from decimal import Decimal

from src.contracts.forecast import BaselineForecastBundle, ForecastStatus, MonthlyForecast
from src.contracts.scenario import MonthlyScenarioAdjustment, ScenarioAdjustmentV2
from src.finance.monthly_scenario import run_monthly_financial_scenario
from src.forecasting.official_features import OfficialFeatureBuilder
from src.orchestration.official_data_pipeline import FakeOfficialAdapter, OfficialDataPipeline
from tests.e2e.support import load_official_observations, load_store, official_requests


def _baseline(store, month: str = "2026-08") -> BaselineForecastBundle:
    point = store.monthly_history[-1].revenue_krw
    return BaselineForecastBundle(
        forecast_id=f"FRC-GOLDEN-{store.store_id}",
        status=ForecastStatus.COMPLETED,
        selected_model="GOLDEN_FIXED",
        model_version="golden.v1",
        available_months=len(store.monthly_history),
        monthly_forecasts=[MonthlyForecast(month=month, point=point, lower=point, upper=point)],
    )


def _neutral(month: str = "2026-08") -> ScenarioAdjustmentV2:
    return ScenarioAdjustmentV2(
        adjustment_id="ADJ-GOLDEN-NEUTRAL",
        scenario="BASELINE",
        months=[MonthlyScenarioAdjustment(month=month)],
    )


def _features(indicators: tuple[str, ...]):
    records = [item for item in load_official_observations() if item["indicator_id"] in indicators]
    bundle = OfficialDataPipeline({"REPLAY": FakeOfficialAdapter(records)}).run(
        "GOLDEN-OFFICIAL",
        date(2026, 7, 31),
        official_requests(indicators),
    )
    return OfficialFeatureBuilder().build(bundle, date(2026, 8, 1), 1)


def test_one_percentage_point_rate_increase_matches_independent_interest_math() -> None:
    store = load_store()
    baseline = _baseline(store)
    neutral = _neutral()
    without_rate = run_monthly_financial_scenario(store, baseline, neutral)
    with_rate = run_monthly_financial_scenario(
        store,
        baseline,
        neutral,
        official_features=_features(("BASE_RATE",)),
    )

    principal = Decimal("80000000")
    expected_base = principal * Decimal("0.063") / Decimal("12")
    expected_increase = principal * Decimal("0.01") / Decimal("12")
    actual_base = without_rate.monthly_cash_flows[0].interest_payment_krw
    actual_with_rate = with_rate.monthly_cash_flows[0].interest_payment_krw

    assert actual_base == expected_base
    assert abs((actual_with_rate - actual_base) - expected_increase) < Decimal("0.000001")


def test_zero_import_exposure_blocks_fx_and_customs_cost_transmission() -> None:
    control = load_store("restaurant_domestic_12m.json")
    exposed = load_store()
    imported_features = _features(("USD_KRW", "IMPORT_UNIT_PRICE_HS090111"))

    control_plain = run_monthly_financial_scenario(control, _baseline(control), _neutral())
    control_official = run_monthly_financial_scenario(
        control, _baseline(control), _neutral(), official_features=imported_features
    )
    exposed_plain = run_monthly_financial_scenario(exposed, _baseline(exposed), _neutral())
    exposed_official = run_monthly_financial_scenario(
        exposed, _baseline(exposed), _neutral(), official_features=imported_features
    )

    assert (
        control_official.monthly_cash_flows[0].variable_costs_cash_krw
        == control_plain.monthly_cash_flows[0].variable_costs_cash_krw
    )
    assert (
        exposed_official.monthly_cash_flows[0].variable_costs_cash_krw
        > exposed_plain.monthly_cash_flows[0].variable_costs_cash_krw
    )
