"""Normalized policy schema used by the deterministic eligibility engine."""
from decimal import Decimal
from typing import List, Optional

from pydantic import Field

from src.contracts.policy_candidate import EligibilityCondition
from src.contracts.research import StrictModel


class PolicySchema(StrictModel):
    policy_id: str
    name: str
    provider: str
    purpose: List[str] = Field(default_factory=lambda: ["WORKING_CAPITAL"])
    region_codes: List[str] = Field(default_factory=list)
    industry_inclusions: List[str] = Field(default_factory=list)
    industry_exclusions: List[str] = Field(default_factory=list)
    limit_krw: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    interest_rate_discount: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    principal_grace_months: int = Field(default=0, ge=0)
    application_start: Optional[str] = None
    application_end: Optional[str] = None
    budget_status: str = "AVAILABLE"
    validation_status: str = "EXTRACTED"
    eligibility_conditions: List[EligibilityCondition] = Field(default_factory=list)
