"""Compatibility facade over the backtested baseline forecasting pipeline."""
from datetime import date
from decimal import Decimal
from typing import Dict, List, Tuple

from src.contracts.store import MonthlyHistory, StoreProfile
from src.forecasting.pipeline import BaselineForecastPipeline


def select_and_forecast_revenue(
    history: List[MonthlyHistory],
    horizon: int,
) -> Tuple[List[Decimal], Dict[str, str]]:
    available_months = len(history)
    bucket = (
        "BASELINE_FALLBACK" if available_months < 6 else
        "LOW_DATA_TREND_AVG" if available_months < 12 else
        "DAMPED_TREND_SEASONAL" if available_months < 24 else
        "SARIMA_ROLLING_BACKTEST"
    )
    declared = history[-1].revenue_krw if history and available_months < 6 else None
    store = StoreProfile(
        store_id="LEGACY-FORECAST",
        address="legacy adapter",
        minimum_operating_cash_krw=Decimal("0"),
        current_cash_krw=Decimal("0"),
        forecast_horizon_months=horizon,
        monthly_history=history,
        declared_monthly_revenue_krw=declared,
    )
    start = date.fromisoformat(history[-1].month + "-01") if history else date.today().replace(day=1)
    bundle = BaselineForecastPipeline().run("LEGACY-FORECAST", store, start)
    metadata = {
        "available_months": str(available_months),
        "model_type": bucket,
        "selected_model": bundle.selected_model or "NONE",
        "interval_kind": str(bundle.interval_kind),
    }
    if bundle.fallback_reason:
        metadata["fallback_reason"] = bundle.fallback_reason
    return [item.point for item in bundle.monthly_forecasts], metadata
