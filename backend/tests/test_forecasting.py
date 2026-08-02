# Unit Tests for Step 3: Official Data Adapters & Forecasting Engine
from decimal import Decimal
import pytest

from src.contracts.store import StoreProfile, MonthlyHistory
from src.ingestion.official_api.ecos import ECOSAdapter
from src.ingestion.official_api.kosis import KOSISAdapter
from src.ingestion.official_api.customs import CustomsAdapter
from src.ingestion.official_api.map_api import MapApiAdapter
from src.forecasting.baseline import NaiveBaselineModel
from src.forecasting.model_selection import select_and_forecast_revenue
from src.forecasting.revenue import forecast_final_revenue
from src.forecasting.cost import forecast_variable_costs, forecast_fixed_costs

def test_official_adapters():
    """Phase 7.1 test."""
    ecos = ECOSAdapter()
    obs_ecos = ecos.process({"indicator_id": "USD_KRW"})
    assert isinstance(obs_ecos, list)

    kosis = KOSISAdapter()
    obs_kosis = kosis.process({})
    assert isinstance(obs_kosis, list)

    customs = CustomsAdapter()
    obs_customs = customs.process({})
    assert isinstance(obs_customs, list)

    # Implementation note.
    map_adapter = MapApiAdapter()
    lat, lon, meta = map_adapter.geocode_address("서울특별시 강남구 테헤란로 123")
    assert lat is None and lon is None
    assert meta["geocode_status"] == "NOT_CONFIGURED"

    # Implementation note.
    lat_fail, lon_fail, meta_fail = map_adapter.geocode_address("미입력 주소")
    assert lat_fail is None
    assert lon_fail is None
    assert meta_fail["geocode_status"] == "NOT_CONFIGURED"


def test_model_selection_horizon_strategies():
    """Phase 13.1 test."""
    # Step 1.
    h_under6 = [MonthlyHistory(month=f"2026-{m:02d}", revenue_krw=Decimal("30000000")) for m in range(1, 4)]
    f_under6, m_under6 = select_and_forecast_revenue(h_under6, horizon=6)
    assert m_under6["model_type"] == "BASELINE_FALLBACK"

    # Step 2.
    h_6_11 = [MonthlyHistory(month=f"2026-{m:02d}", revenue_krw=Decimal("30000000")) for m in range(1, 9)]
    f_6_11, m_6_11 = select_and_forecast_revenue(h_6_11, horizon=6)
    assert m_6_11["model_type"] == "LOW_DATA_TREND_AVG"

    # Step 3.
    h_12_23 = [MonthlyHistory(month=f"2025-{m:02d}", revenue_krw=Decimal("30000000")) for m in range(1, 13)]
    f_12_23, m_12_23 = select_and_forecast_revenue(h_12_23, horizon=6)
    assert m_12_23["model_type"] == "DAMPED_TREND_SEASONAL"

    # Step 4.
    h_24 = [MonthlyHistory(month=f"2025-{m:02d}", revenue_krw=Decimal("30000000")) for m in range(1, 13)] * 2
    f_24, m_24 = select_and_forecast_revenue(h_24, horizon=6)
    assert m_24["model_type"] == "SARIMA_ROLLING_BACKTEST"


def test_revenue_and_cost_forecasting():
    """Phase 13.2 test."""
    store = StoreProfile(
        store_id="STORE-FORECAST-01",
        address="서울특별시 강남구",
        minimum_operating_cash_krw=Decimal("5000000"),
        current_cash_krw=Decimal("10000000"),
        forecast_horizon_months=6,
        monthly_history=[
            MonthlyHistory(month="2026-07", revenue_krw=Decimal("30000000"))
        ]
    )

    # Step 1.
    rev_forecasts, meta = forecast_final_revenue(store, revenue_multiplier=Decimal("0.9"))
    assert rev_forecasts[0] == Decimal("27000000")

    # Step 2.
    var_costs = forecast_variable_costs(
        revenue_forecasts=rev_forecasts,
        base_ratio=Decimal("0.4"),
        imported_share=Decimal("0.25"),
        fx_change_rate=Decimal("0.10"),
        pass_through_rate=Decimal("0.80"),
    )
    assert var_costs[0] == Decimal("11016000")

    # Step 3.
    fixed_costs = forecast_fixed_costs(store, horizon=6, minimum_wage_increase_rate=Decimal("0.05"))
    assert len(fixed_costs) == 6
