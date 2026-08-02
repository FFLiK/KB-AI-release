"""Versioned store profile and financial input contracts."""
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from pydantic import ConfigDict, Field

from src.contracts.loan import Loan
from src.contracts.research import StrictModel


class MonthlyCostDetail(StrictModel):
    ingredients_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    platform_fee_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    payment_fee_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class MonthlyFixedCostDetail(StrictModel):
    rent_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    labor_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    utilities_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    other_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class FixedCostScheduleEntry(StrictModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    category: Literal["rent", "labor", "utilities", "other"]
    amount_krw: Decimal = Field(ge=Decimal("0"))
    source: str = "USER_DECLARED"


class MonthlyHistory(StrictModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")
    revenue_krw: Decimal = Field(ge=Decimal("0"))
    transaction_count: int = Field(default=0, ge=0)
    variable_costs: MonthlyCostDetail = Field(default_factory=MonthlyCostDetail)
    fixed_costs: MonthlyFixedCostDetail = Field(default_factory=MonthlyFixedCostDetail)
    tax_cash_outflow_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    capital_expenditure_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class CostExposures(StrictModel):
    imported_ingredient_share: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1"))
    variable_rate_debt_share: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), le=Decimal("1"))


class StoreProfile(StrictModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    store_id: str
    business_start_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    annual_revenue_krw: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    employee_count: Optional[int] = Field(default=None, ge=0)
    credit_band: Optional[str] = None
    owner_age: Optional[int] = Field(default=None, ge=0, le=120)
    business_type_code: str = Field(default="FNB_CAFE", description="Industry code")
    address: str
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    opening_hours: Optional[Dict[str, List[List[str]]]] = None
    forecast_horizon_months: int = Field(default=6, ge=1, le=12)
    minimum_operating_cash_krw: Decimal = Field(ge=Decimal("0"))
    current_cash_krw: Decimal = Field(ge=Decimal("0"))
    declared_monthly_revenue_krw: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    monthly_history: List[MonthlyHistory] = Field(default_factory=list)
    fixed_cost_schedule: List[FixedCostScheduleEntry] = Field(default_factory=list)
    loans: List[Loan] = Field(default_factory=list)
    cost_exposures: CostExposures = Field(default_factory=CostExposures)
    schema_version: str = "store_profile.v1"


StoreProfile.model_rebuild()
