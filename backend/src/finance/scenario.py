# Phase 17 implementation note.
from decimal import Decimal
from typing import Dict, List, Optional
from src.contracts.store import StoreProfile
from src.contracts.loan import Loan
from src.contracts.financial import (
    MonthlyCashFlow,
    BEPResult,
    FinancialScenarioResult,
)
from src.finance.loan import calculate_loan_schedule
from src.finance.break_even import calculate_bep
from src.finance.cashflow import (
    calculate_monthly_cashflow,
    evaluate_cash_burn_and_liquidity_risk,
)

def run_financial_scenario(
    store_profile: StoreProfile,
    scenario_name: str = "BASELINE",
    revenue_multiplier: Decimal = Decimal("1.0"),
    variable_cost_multiplier: Decimal = Decimal("1.0"),
    fixed_cost_multiplier: Decimal = Decimal("1.0"),
    interest_rate_delta: Decimal = Decimal("0.0"),
    base_month_str: str | None = None,
) -> FinancialScenarioResult:
    """Phase 17 documentation."""
    horizon = store_profile.forecast_horizon_months
    
    # Phase 15 implementation note.
    loan_schedules = []
    loan_metadata_combined = {}
    for loan in store_profile.loans:
        sch, meta = calculate_loan_schedule(loan, horizon, rate_change_delta=interest_rate_delta)
        loan_schedules.append(sch)
        loan_metadata_combined.update(meta)

    # Implementation note.
    if not store_profile.monthly_history:
        raise ValueError("INSUFFICIENT_DATA: revenue and cost history are required")
    last_history = store_profile.monthly_history[-1]
    base_rev = last_history.revenue_krw
    if base_month_str is None:
        history_year, history_month = (int(part) for part in last_history.month.split("-"))
        next_index = history_year * 12 + history_month
        base_month_str = f"{next_index // 12:04d}-{next_index % 12 + 1:02d}"
    
    base_var_cost = (
        last_history.variable_costs.ingredients_krw
        + last_history.variable_costs.platform_fee_krw
        + last_history.variable_costs.payment_fee_krw
    )
    
    base_fixed_cost = (
        last_history.fixed_costs.rent_krw
        + last_history.fixed_costs.labor_krw
        + last_history.fixed_costs.utilities_krw
        + last_history.fixed_costs.other_krw
    )
    
    base_tax = last_history.tax_cash_outflow_krw
    base_capex = last_history.capital_expenditure_krw

    # Implementation note.
    monthly_cash_flows: List[MonthlyCashFlow] = []
    bep_results: List[BEPResult] = []
    
    curr_cash = store_profile.current_cash_krw
    
    year_str, month_str = base_month_str.split("-")
    base_year, base_month_int = int(year_str), int(month_str)

    for t in range(1, horizon + 1):
        # Implementation note.
        curr_m_int = (base_month_int - 1 + (t - 1)) % 12 + 1
        curr_y_int = base_year + (base_month_int - 1 + (t - 1)) // 12
        curr_m_str = f"{curr_y_int:04d}-{curr_m_int:02d}"

        # Phase 13.2 implementation note.
        rev_forecast = base_rev * revenue_multiplier
        var_cost_forecast = base_var_cost * variable_cost_multiplier
        fixed_cost_forecast = base_fixed_cost * fixed_cost_multiplier

        # Implementation note.
        interest_sum = Decimal("0")
        principal_sum = Decimal("0")
        for sch in loan_schedules:
            if len(sch) >= t:
                interest_sum += sch[t - 1].interest_payment_krw
                principal_sum += sch[t - 1].principal_payment_krw

        # Phase 16.1 implementation note.
        bep_res = calculate_bep(
            month_index=t,
            revenue_forecast_krw=rev_forecast,
            total_variable_cost_krw=var_cost_forecast,
            operating_fixed_cost_krw=fixed_cost_forecast,
            interest_expense_krw=interest_sum,
            principal_payment_krw=principal_sum,
            tax_cash_outflow_krw=base_tax,
            capital_expenditure_krw=base_capex,
        )
        bep_results.append(bep_res)

        # Phase 16.3 implementation note.
        cf_res = calculate_monthly_cashflow(
            month_index=t,
            month_str=curr_m_str,
            beginning_cash_krw=curr_cash,
            revenue_cash_krw=rev_forecast,
            variable_costs_cash_krw=var_cost_forecast,
            fixed_costs_cash_krw=fixed_cost_forecast,
            interest_payment_krw=interest_sum,
            principal_payment_krw=principal_sum,
            tax_cash_outflow_krw=base_tax,
            capital_expenditure_krw=base_capex,
        )
        monthly_cash_flows.append(cf_res)
        curr_cash = cf_res.ending_cash_krw

    # Phase 16.4 implementation note.
    cash_burn_res = evaluate_cash_burn_and_liquidity_risk(
        monthly_cash_flows=monthly_cash_flows,
        minimum_operating_cash_krw=store_profile.minimum_operating_cash_krw,
    )

    metadata = {
        "scenario_name": scenario_name,
        "revenue_multiplier": str(revenue_multiplier),
        "interest_rate_delta": str(interest_rate_delta),
    }
    metadata.update(loan_metadata_combined)

    return FinancialScenarioResult(
        scenario_name=scenario_name,
        monthly_cash_flows=monthly_cash_flows,
        bep_results=bep_results,
        cash_burn_result=cash_burn_res,
        metadata=metadata,
    )
