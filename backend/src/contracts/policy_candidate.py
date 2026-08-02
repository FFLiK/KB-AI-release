from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import Field

from src.contracts.event_candidate import EvidenceRef
from src.contracts.research import StrictModel


class PolicyType(str, Enum):
    LOAN_SUPPORT = "LOAN_SUPPORT"
    CREDIT_GUARANTEE = "CREDIT_GUARANTEE"
    INTEREST_SUBSIDY = "INTEREST_SUBSIDY"
    GRANT = "GRANT"
    REPAYMENT_DEFERRAL = "REPAYMENT_DEFERRAL"
    TAX_RELIEF = "TAX_RELIEF"


class EligibilityCondition(StrictModel):
    field_path: str
    operator: str
    expected_value: str | int | Decimal | bool | None = None
    unit: str | None = None


class InterestTerms(StrictModel):
    annual_rate_percent: Decimal | None = Field(default=None, ge=0)
    rate_discount_percentage_points: Decimal | None = Field(default=None, ge=0)


class GuaranteeTerms(StrictModel):
    coverage_ratio: Decimal | None = Field(default=None, ge=0, le=1)
    guarantee_fee_percent: Decimal | None = Field(default=None, ge=0)
    collateral_required: bool | None = None


class RepaymentTerms(StrictModel):
    principal_grace_months: int | None = Field(default=None, ge=0)
    maturity_months: int | None = Field(default=None, ge=0)
    repayment_method: str | None = None


class PolicyCandidate(StrictModel):
    policy_candidate_id: str
    extractor_policy_candidate_id: str | None = None
    identity_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    policy_merge_group_id: str | None = None
    merged_policy_candidate_ids: list[str] = Field(default_factory=list)
    research_run_id: str
    policy_type: PolicyType
    name: str
    provider_raw: str
    purpose: list[str] = Field(default_factory=list)
    region_codes: list[str] = Field(default_factory=list)
    industry_inclusions_raw: list[str] = Field(default_factory=list)
    industry_exclusions_raw: list[str] = Field(default_factory=list)
    limit_krw: Decimal | None = Field(default=None, ge=0)
    interest_terms: InterestTerms = Field(default_factory=InterestTerms)
    guarantee_terms: GuaranteeTerms = Field(default_factory=GuaranteeTerms)
    repayment_terms: RepaymentTerms = Field(default_factory=RepaymentTerms)
    application_start: date | None = None
    application_end: date | None = None
    budget_status: str = "UNKNOWN"
    application_status: str = "STATUS_UNCONFIRMED"
    recommendation_failure_codes: list[str] = Field(default_factory=list)
    eligibility_conditions: list[EligibilityCondition] = Field(default_factory=list)
    source_ids: list[str] = Field(min_length=1)
    evidence: list[EvidenceRef] = Field(min_length=1)
    supersedes_policy_candidate_id: str | None = None
    notice_kind: str = "ORIGINAL"
    validation_status: str = "EXTRACTED"
    validation_failure_codes: list[str] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    source_validation_details: list[dict[str, object]] = Field(default_factory=list)
    schema_version: str = "policy_candidate.v1"
