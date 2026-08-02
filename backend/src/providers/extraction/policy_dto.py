"""Provider-safe DTO and schema for policy extraction."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from pydantic import Field

from src.contracts.policy_candidate import PolicyCandidate, PolicyType
from src.contracts.research import StrictModel


class PolicyEvidenceDTO(StrictModel):
    evidence_id: str
    source_id: str
    source_revision_id: str
    field_paths: list[str]
    quote: str
    start_offset: int
    end_offset: int


class EligibilityConditionDTO(StrictModel):
    field_path: str
    operator: str
    expected_value: str | None = None
    unit: str | None = None


class PolicyCandidateDTO(StrictModel):
    policy_candidate_id: str
    extractor_policy_candidate_id: str | None = None
    identity_fingerprint: str | None = None
    policy_merge_group_id: str | None = None
    merged_policy_candidate_ids: list[str] = Field(default_factory=list)
    research_run_id: str
    policy_type: str
    name: str
    provider_raw: str
    purpose: list[str] = Field(default_factory=list)
    region_codes: list[str] = Field(default_factory=list)
    industry_inclusions_raw: list[str] = Field(default_factory=list)
    industry_exclusions_raw: list[str] = Field(default_factory=list)
    limit_krw: Decimal | None = None
    interest_terms: dict[str, float | None] = Field(default_factory=dict)
    guarantee_terms: dict[str, float | bool | None] = Field(default_factory=dict)
    repayment_terms: dict[str, int | str | None] = Field(default_factory=dict)
    application_start: str | None = None
    application_end: str | None = None
    application_status: str = "UNKNOWN"
    availability_status: str = "BUDGET_UNKNOWN"
    budget_status: str = "UNKNOWN"
    last_updated: str | None = None
    recommendation_failure_codes: list[str] = Field(default_factory=list)
    current_notice_revision: str | None = None
    application_rounds: list[dict[str, str | None]] = Field(default_factory=list)
    eligibility_conditions: list[EligibilityConditionDTO] = Field(default_factory=list)
    source_ids: list[str]
    evidence: list[PolicyEvidenceDTO]
    supersedes_policy_candidate_id: str | None = None
    notice_kind: str = "ORIGINAL"
    validation_status: str = "EXTRACTED"
    validation_failure_codes: list[str] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)
    schema_version: str = "policy_candidate.v1"

    def to_domain(self) -> PolicyCandidate:
        payload = self.model_dump(mode="json")
        payload["policy_type"] = _normalize_policy_type(self.policy_type)
        for field_name in (
            "policy_merge_group_id", "merged_policy_candidate_ids",
            "application_status", "availability_status", "last_updated",
            "current_notice_revision", "application_rounds",
        ):
            payload.pop(field_name, None)
        # Provider output permits a simple string, while the domain uses an enum.
        # Normalize established aliases so valid policies are not discarded.
        return PolicyCandidate.model_validate(payload)


class PolicyExtractionResponseDTO(StrictModel):
    policies: list[PolicyCandidateDTO]


def _nullable(kind: str) -> dict:
    return {"type": [kind, "null"]}

def _normalize_policy_type(raw: str) -> str:
    normalized = raw.strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "loan": PolicyType.LOAN_SUPPORT.value,
        "loan_support": PolicyType.LOAN_SUPPORT.value,
        "loan_program": PolicyType.LOAN_SUPPORT.value,
        "credit_guarantee": PolicyType.CREDIT_GUARANTEE.value,
        "credit_guarantee_support": PolicyType.CREDIT_GUARANTEE.value,
        "guarantee": PolicyType.CREDIT_GUARANTEE.value,
        "interest_subsidy": PolicyType.INTEREST_SUBSIDY.value,
        "interest_support": PolicyType.INTEREST_SUBSIDY.value,
        "loan_interest_subsidy": PolicyType.INTEREST_SUBSIDY.value,
        "loan_interest_support": PolicyType.INTEREST_SUBSIDY.value,
        "grant": PolicyType.GRANT.value,
        "repayment_deferral": PolicyType.REPAYMENT_DEFERRAL.value,
        "tax_relief": PolicyType.TAX_RELIEF.value,
    }
    return aliases.get(normalized, raw)



def _object(properties: dict[str, dict]) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


def policy_extraction_response_schema() -> dict:
    """Strict Outputs schema restricted to primitives, arrays, and objects."""
    text = {"type": "string"}
    number = {"type": "number"}
    integer = {"type": "integer"}
    evidence = _object({"evidence_id": text, "source_id": text, "source_revision_id": text, "field_paths": {"type": "array", "items": text}, "quote": text, "start_offset": integer, "end_offset": integer})
    eligibility = _object({"field_path": text, "operator": text, "expected_value": _nullable("string"), "unit": _nullable("string")})
    application_round = _object({"name": _nullable("string"), "start_date": _nullable("string"), "end_date": _nullable("string")})
    policy = _object({
        "policy_candidate_id": text, "extractor_policy_candidate_id": _nullable("string"), "identity_fingerprint": _nullable("string"), "research_run_id": text,
        "policy_type": {"type": "string", "enum": [item.value for item in PolicyType]}, "name": text, "provider_raw": text,
        "purpose": {"type": "array", "items": text}, "region_codes": {"type": "array", "items": text}, "industry_inclusions_raw": {"type": "array", "items": text}, "industry_exclusions_raw": {"type": "array", "items": text}, "limit_krw": _nullable("number"),
        "interest_terms": _object({"annual_rate_percent": _nullable("number"), "rate_discount_percentage_points": _nullable("number")}),
        "guarantee_terms": _object({"coverage_ratio": _nullable("number"), "guarantee_fee_percent": _nullable("number"), "collateral_required": _nullable("boolean")} ),
        "repayment_terms": _object({"principal_grace_months": _nullable("integer"), "maturity_months": _nullable("integer"), "repayment_method": _nullable("string")}),
        "application_start": _nullable("string"), "application_end": _nullable("string"), "budget_status": text,
        "eligibility_conditions": {"type": "array", "items": eligibility}, "source_ids": {"type": "array", "items": text}, "evidence": {"type": "array", "items": evidence}, "supersedes_policy_candidate_id": _nullable("string"), "notice_kind": text, "validation_status": text, "validation_failure_codes": {"type": "array", "items": text}, "validation_notes": {"type": "array", "items": text}, "schema_version": text,
    })
    return _object({"policies": {"type": "array", "items": policy}})


def provider_policy_schema() -> dict:
    return deepcopy(policy_extraction_response_schema())
