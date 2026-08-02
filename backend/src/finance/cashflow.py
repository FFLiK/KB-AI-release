"""Monthly cash-flow and liquidity calculations."""
import calendar
from decimal import Decimal
from typing import List, Optional

from src.contracts.financial import CashBurnResult, MonthlyCashFlow


def calculate_monthly_cashflow(
    month_index: int,
    month_str: str,
    beginning_cash_krw: Decimal,
    revenue_cash_krw: Decimal,
    variable_costs_cash_krw: Decimal,
    fixed_costs_cash_krw: Decimal,
    interest_payment_krw: Decimal,
    principal_payment_krw: Decimal,
    tax_cash_outflow_krw: Decimal = Decimal("0"),
    capital_expenditure_krw: Decimal = Decimal("0"),
    other_cash_inflows_krw: Decimal = Decimal("0"),
    ingredient_costs_cash_krw: Decimal = Decimal("0"),
    other_variable_costs_cash_krw: Decimal = Decimal("0"),
) -> MonthlyCashFlow:
    net_cash_flow_krw = (
        revenue_cash_krw
        - variable_costs_cash_krw
        - fixed_costs_cash_krw
        - interest_payment_krw
        - principal_payment_krw
        - tax_cash_outflow_krw
        - capital_expenditure_krw
        + other_cash_inflows_krw
    )
    ending_cash_krw = beginning_cash_krw + net_cash_flow_krw

    return MonthlyCashFlow(
        month_index=month_index,
        month_str=month_str,
        beginning_cash_krw=beginning_cash_krw,
        revenue_cash_krw=revenue_cash_krw,
        variable_costs_cash_krw=variable_costs_cash_krw,
        ingredient_costs_cash_krw=ingredient_costs_cash_krw,
        other_variable_costs_cash_krw=other_variable_costs_cash_krw,
        fixed_costs_cash_krw=fixed_costs_cash_krw,
        interest_payment_krw=interest_payment_krw,
        principal_payment_krw=principal_payment_krw,
        tax_cash_outflow_krw=tax_cash_outflow_krw,
        capital_expenditure_krw=capital_expenditure_krw,
        other_cash_inflows_krw=other_cash_inflows_krw,
        net_cash_flow_krw=net_cash_flow_krw,
        ending_cash_krw=ending_cash_krw,
    )


def evaluate_cash_burn_and_liquidity_risk(
    monthly_cash_flows: List[MonthlyCashFlow],
    minimum_operating_cash_krw: Decimal,
) -> CashBurnResult:
    burn_month_obj: Optional[MonthlyCashFlow] = None
    liquidity_month_obj: Optional[MonthlyCashFlow] = None
    for cash_flow in monthly_cash_flows:
        if cash_flow.ending_cash_krw <= Decimal("0") and burn_month_obj is None:
            burn_month_obj = cash_flow
        if cash_flow.ending_cash_krw <= minimum_operating_cash_krw and liquidity_month_obj is None:
            liquidity_month_obj = cash_flow

    liquidity_risk_date = (
        f"{liquidity_month_obj.month_str}-01" if liquidity_month_obj else None
    )
    if burn_month_obj is None:
        return CashBurnResult(
            cash_burn_date=None,
            cash_burn_month=None,
            days_to_burn=None,
            liquidity_risk_date=liquidity_risk_date,
            horizon_status="NO_BURN_WITHIN_HORIZON",
            calculation_assumption="MONTHLY_EVEN_DISTRIBUTION",
        )

    year_str, month_str = burn_month_obj.month_str.split("-")
    days_in_month = calendar.monthrange(int(year_str), int(month_str))[1]
    beginning_cash = burn_month_obj.beginning_cash_krw
    absolute_net_flow = abs(burn_month_obj.net_cash_flow_krw)
    if beginning_cash <= Decimal("0"):
        days_to_burn = Decimal("1")
        cash_burn_date = f"{burn_month_obj.month_str}-01"
    elif absolute_net_flow > Decimal("0"):
        days_to_burn = Decimal(days_in_month) * beginning_cash / absolute_net_flow
        burn_day = max(1, min(days_in_month, int(days_to_burn)))
        cash_burn_date = f"{burn_month_obj.month_str}-{burn_day:02d}"
    else:
        days_to_burn = Decimal(days_in_month)
        cash_burn_date = f"{burn_month_obj.month_str}-{days_in_month:02d}"

    return CashBurnResult(
        cash_burn_date=cash_burn_date,
        cash_burn_month=burn_month_obj.month_index,
        days_to_burn=days_to_burn,
        liquidity_risk_date=liquidity_risk_date,
        horizon_status="BURN_WITHIN_HORIZON",
        calculation_assumption="MONTHLY_EVEN_DISTRIBUTION",
    )
