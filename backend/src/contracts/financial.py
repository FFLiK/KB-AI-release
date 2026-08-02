"""Financial calculation contracts."""
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import Field

from src.contracts.research import StrictModel


class MonthlyLoanPayment(StrictModel):
    loan_id: str
    month_index: int = Field(ge=1)
    opening_balance_krw: Decimal
    interest_payment_krw: Decimal
    principal_payment_krw: Decimal
    closing_balance_krw: Decimal
    applied_annual_rate: Decimal


class MonthlyCashFlow(StrictModel):
    month_index: int = Field(ge=1)
    month_str: str = Field(description="YYYY-MM")
    beginning_cash_krw: Decimal
    revenue_cash_krw: Decimal
    variable_costs_cash_krw: Decimal
    ingredient_costs_cash_krw: Decimal = Decimal("0")
    other_variable_costs_cash_krw: Decimal = Decimal("0")
    fixed_costs_cash_krw: Decimal
    interest_payment_krw: Decimal
    principal_payment_krw: Decimal
    tax_cash_outflow_krw: Decimal
    capital_expenditure_krw: Decimal
    other_cash_inflows_krw: Decimal = Decimal("0")
    net_cash_flow_krw: Decimal
    ending_cash_krw: Decimal


class BEPResult(StrictModel):
    month_index: int = Field(ge=1)
    revenue_forecast_krw: Decimal
    variable_cost_ratio: Decimal
    contribution_margin_ratio: Decimal
    operating_bep_krw: Optional[Decimal] = Field(default=None)
    financial_bep_krw: Optional[Decimal] = Field(default=None)
    cash_bep_krw: Optional[Decimal] = Field(default=None)
    bep_status: str = Field(default="NORMAL", description="NORMAL or UNATTAINABLE")
    bep_failure_reason: Optional[str] = Field(default=None)


class CashBurnResult(StrictModel):
    cash_burn_date: Optional[str] = Field(default=None)
    cash_burn_month: Optional[int] = Field(default=None)
    days_to_burn: Optional[Decimal] = Field(default=None)
    liquidity_risk_date: Optional[str] = Field(default=None)
    horizon_status: str = Field(default="BURN_WITHIN_HORIZON")
    calculation_assumption: str = Field(default="MONTHLY_EVEN_DISTRIBUTION")


class FinancialScenarioResult(StrictModel):
    scenario_name: str = Field(description="BASELINE, LOW_IMPACT, or HIGH_IMPACT")
    monthly_cash_flows: List[MonthlyCashFlow]
    bep_results: List[BEPResult]
    cash_burn_result: CashBurnResult
    metadata: Dict[str, str] = Field(default_factory=dict)
