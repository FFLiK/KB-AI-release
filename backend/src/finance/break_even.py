# Phase 16.1 implementation note.
from decimal import Decimal
from src.contracts.financial import BEPResult

def calculate_bep(
    month_index: int,
    revenue_forecast_krw: Decimal,
    total_variable_cost_krw: Decimal,
    operating_fixed_cost_krw: Decimal,
    interest_expense_krw: Decimal,
    principal_payment_krw: Decimal,
    tax_cash_outflow_krw: Decimal = Decimal("0"),
    capital_expenditure_krw: Decimal = Decimal("0"),
) -> BEPResult:
    """Phase 16.1 documentation."""
    # Phase 16.1 implementation note.
    if revenue_forecast_krw <= Decimal("0"):
        variable_cost_ratio = Decimal("1.0")
        cm_ratio = Decimal("0.0")
    else:
        variable_cost_ratio = total_variable_cost_krw / revenue_forecast_krw
        cm_ratio = Decimal("1") - variable_cost_ratio

    # Step 2.
    if cm_ratio <= Decimal("0"):
        return BEPResult(
            month_index=month_index,
            revenue_forecast_krw=revenue_forecast_krw,
            variable_cost_ratio=variable_cost_ratio,
            contribution_margin_ratio=cm_ratio,
            operating_bep_krw=None,
            financial_bep_krw=None,
            cash_bep_krw=None,
            bep_status="UNATTAINABLE",
            bep_failure_reason="CONTRIBUTION_MARGIN_RATIO_NON_POSITIVE",
        )

    # Phase 16.2 implementation note.
    # Operating BEP = OperatingFixedCosts / CM_Ratio
    operating_bep = operating_fixed_cost_krw / cm_ratio

    # Financial BEP = (OperatingFixedCosts + InterestExpense) / CM_Ratio
    financial_bep = (operating_fixed_cost_krw + interest_expense_krw) / cm_ratio

    # Cash BEP = (CashFixedOutflows + InterestPayment + PrincipalPayment + Tax + CapEx) / CM_Ratio
    total_cash_fixed_outflow = (
        operating_fixed_cost_krw
        + interest_expense_krw
        + principal_payment_krw
        + tax_cash_outflow_krw
        + capital_expenditure_krw
    )
    cash_bep = total_cash_fixed_outflow / cm_ratio

    return BEPResult(
        month_index=month_index,
        revenue_forecast_krw=revenue_forecast_krw,
        variable_cost_ratio=variable_cost_ratio,
        contribution_margin_ratio=cm_ratio,
        operating_bep_krw=operating_bep,
        financial_bep_krw=financial_bep,
        cash_bep_krw=cash_bep,
        bep_status="NORMAL",
        bep_failure_reason=None,
    )
