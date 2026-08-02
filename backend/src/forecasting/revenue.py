# Phase 13.2 implementation note.
from decimal import Decimal
from typing import Dict, List, Tuple
from src.contracts.store import StoreProfile
from src.forecasting.model_selection import select_and_forecast_revenue

def forecast_final_revenue(
    store_profile: StoreProfile,
    revenue_multiplier: Decimal = Decimal("1.0"),
) -> Tuple[List[Decimal], Dict[str, str]]:
    """Phase 13.2 documentation."""
    horizon = store_profile.forecast_horizon_months
    history = store_profile.monthly_history

    # Phase 13.1 implementation note.
    baseline_forecasts, metadata = select_and_forecast_revenue(history, horizon)

    # Phase 13.2 implementation note.
    final_forecasts = [b * revenue_multiplier for b in baseline_forecasts]
    
    metadata["revenue_multiplier_applied"] = str(revenue_multiplier)

    return final_forecasts, metadata
