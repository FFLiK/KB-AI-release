# Phase 14.1 implementation note.
from decimal import Decimal
from typing import Dict, List, Tuple
from src.contracts.store import StoreProfile

def forecast_variable_costs(
    revenue_forecasts: List[Decimal],
    base_ratio: Decimal = Decimal("0.4"),
    imported_share: Decimal = Decimal("0.25"),
    fx_change_rate: Decimal = Decimal("0.0"),  # Step 0.
    pass_through_rate: Decimal = Decimal("0.8"),  # Implementation note.
) -> List[Decimal]:
    """Phase 14.1 documentation."""
    import_share = imported_share
    domestic_share = Decimal("1.0") - import_share

    cost_multiplier = Decimal("1.0") + (import_share * pass_through_rate * fx_change_rate)

    variable_costs = []
    for rev in revenue_forecasts:
        v_cost = rev * base_ratio * cost_multiplier
        variable_costs.append(v_cost)

    return variable_costs

def forecast_fixed_costs(
    store_profile: StoreProfile,
    horizon: int,
    minimum_wage_increase_rate: Decimal = Decimal("0.0"),
) -> List[Decimal]:
    """Phase 14.2 documentation."""
    if not store_profile.monthly_history:
        raise ValueError("INSUFFICIENT_DATA: fixed-cost history is required")
    last_history = store_profile.monthly_history[-1]
    base_rent = last_history.fixed_costs.rent_krw
    base_labor = last_history.fixed_costs.labor_krw
    base_utilities = last_history.fixed_costs.utilities_krw
    base_other = last_history.fixed_costs.other_krw

    adjusted_labor = base_labor * (Decimal("1.0") + minimum_wage_increase_rate)
    monthly_fixed_sum = base_rent + adjusted_labor + base_utilities + base_other

    return [monthly_fixed_sum] * horizon
