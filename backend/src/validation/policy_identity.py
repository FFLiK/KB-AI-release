"""Stable, source-independent semantic policy identity."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from urllib.parse import urlsplit

from src.source_snapshot.source_policy import source_authority

from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.source_document import SourceDocument
from src.normalization.region_normalizer import canonical_region_ids


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]+", "", _normalized(value))


def _policy_type(policy: PolicyCandidate) -> str:
    return getattr(policy.policy_type, "value", str(policy.policy_type))


def normalized_policy_provider(value: str) -> str:
    text = _compact(value)
    for suffix in (
        "foundation", "corporation", "agency", "office",
        "\uc7ac\ub2e8", "\uacf5\ub2e8", "\uacf5\uc0ac", "\uc8fc\uc2dd\ud68c\uc0ac",
    ):
        text = text.removesuffix(suffix)
    return text


def policy_provider_authority(
    policy: PolicyCandidate,
    documents: dict[str, SourceDocument] | None = None,
) -> str:
    """Resolve an official source authority before comparing raw provider labels."""
    docs = documents or {}
    authorities: set[str] = set()
    hosts: set[str] = set()
    for source_id in policy.source_ids:
        document = docs.get(source_id)
        if document is None:
            continue
        authority = source_authority(document.canonical_url)
        governing = (authority or {}).get("governing_authority")
        if governing:
            authorities.add(_compact(governing))
        host = (urlsplit(document.canonical_url).hostname or "").lower()
        if host:
            hosts.add(host)
    if len(authorities) == 1:
        return next(iter(authorities))
    if len(hosts) == 1:
        return "host:" + next(iter(hosts))
    return normalized_policy_provider(policy.provider_raw)
def normalized_policy_name(value: str) -> str:
    text = _compact(value)
    aliases = (
        ("creditguaranteesupport", "creditguarantee"),
        ("specialcreditguarantee", "creditguarantee"),
        ("\ud2b9\ubcc4\uc2e0\uc6a9\ubcf4\uc99d\uc9c0\uc6d0", "\uc2e0\uc6a9\ubcf4\uc99d"),
        ("\uc2e0\uc6a9\ubcf4\uc99d\uc9c0\uc6d0", "\uc2e0\uc6a9\ubcf4\uc99d"),
        ("\uc2e0\uc6a9\ubcf4\uc99d\uc81c\ub3c4", "\uc2e0\uc6a9\ubcf4\uc99d"),
    )
    for source, target in aliases:
        text = text.replace(source, target)
    text = re.sub(r"20\d{2}", "", text)
    for token in (
        "program", "policy", "support", "special",
        "\uac15\ub0a8\uad6c", "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc", "\uc11c\uc6b8\uc2dc",
        "\uc911\uc18c\uae30\uc5c5", "\uc18c\uc0c1\uacf5\uc778", "\ud2b9\ubcc4", "\uc0ac\uc5c5", "\uc9c0\uc6d0",
    ):
        text = text.replace(token, "")
    return text


def _program_years(policy: PolicyCandidate, documents: dict[str, SourceDocument]) -> tuple[str, ...]:
    preferred = [policy.name]
    preferred.extend(
        documents[source_id].title
        for source_id in policy.source_ids
        if source_id in documents
    )
    for values in (preferred, [item.quote for item in policy.evidence]):
        years = sorted({match.group(0) for value in values for match in re.finditer(r"20\d{2}", value)})
        if years:
            return tuple(years)
    return ()


def _purpose_signature(values: Iterable[str]) -> tuple[str, ...]:
    text = " ".join(_normalized(value) for value in values)
    signatures = {
        key for key, tokens in {
            "WORKING_CAPITAL": ("working capital", "\uc6b4\uc804\uc790\uae08"),
            "FACILITY": ("facility", "equipment", "\uc2dc\uc124\uc790\uae08", "\uc124\ube44"),
            "CREDIT_GUARANTEE": ("credit guarantee", "guarantee", "\uc2e0\uc6a9\ubcf4\uc99d", "\ubcf4\uc99d\uc11c"),
            "INTEREST_REDUCTION": ("interest", "rate subsidy", "\uc774\uc790", "\uae08\ub9ac"),
            "DEBT_RELIEF": ("debt", "repayment", "\ucc44\ubb34", "\uc0c1\ud658"),
        }.items()
        if any(token in text for token in tokens)
    }
    return tuple(sorted(signatures))


def _normalized_values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({_normalized(value) for value in values if _normalized(value)}))


def _eligibility_map(policy: PolicyCandidate) -> dict[str, tuple[str, str]]:
    return {
        _normalized(item.field_path): (
            _normalized(item.operator), _normalized(str(item.expected_value or ""))
        )
        for item in policy.eligibility_conditions
    }


def _status_class(policy: PolicyCandidate) -> str:
    status = policy.application_status.upper()
    if status in {"CLOSED", "BUDGET_EXHAUSTED"} or policy.notice_kind == "TERMINATION":
        return "CLOSED"
    if status == "OPEN":
        return "OPEN"
    if status == "SCHEDULED":
        return "SCHEDULED"
    return "UNKNOWN"


def semantic_policy_identity_parts(
    policy: PolicyCandidate,
    documents: dict[str, SourceDocument] | None = None,
) -> tuple[str, ...]:
    docs = documents or {}
    return (
        policy_provider_authority(policy, docs),
        normalized_policy_name(policy.name),
        _policy_type(policy),
        ",".join(_program_years(policy, docs)),
        ",".join(canonical_region_ids(policy.region_codes)),
        ",".join(_purpose_signature(policy.purpose)),
        ",".join(_normalized_values(policy.industry_inclusions_raw)),
        ",".join(_normalized_values(policy.industry_exclusions_raw)),
        _status_class(policy),
        policy.application_start.isoformat() if policy.application_start else "",
        policy.application_end.isoformat() if policy.application_end else "",
        str(policy.limit_krw or ""),
        str(policy.interest_terms.annual_rate_percent or ""),
        str(policy.interest_terms.rate_discount_percentage_points or ""),
        str(policy.guarantee_terms.coverage_ratio or ""),
        str(policy.guarantee_terms.guarantee_fee_percent or ""),
        str(policy.repayment_terms.principal_grace_months or ""),
        str(policy.repayment_terms.maturity_months or ""),
        _normalized(str(policy.repayment_terms.repayment_method or "")),
        str(policy.guarantee_terms.collateral_required),
        ",".join(
            f"{key}:{operator}:{value}"
            for key, (operator, value) in sorted(_eligibility_map(policy).items())
        ),
    )


def policy_identity_fingerprint(
    policy: PolicyCandidate,
    documents: dict[str, SourceDocument],
) -> str:
    material = "|".join(semantic_policy_identity_parts(policy, documents))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _compatible_optional(left: object, right: object) -> bool:
    return left is None or right is None or left == right


def policies_semantically_equivalent(
    left: PolicyCandidate,
    right: PolicyCandidate,
    documents: dict[str, SourceDocument] | None = None,
) -> bool:
    """Match the same revision across sources while failing closed on material differences."""
    docs = documents or {}
    if _policy_type(left) != _policy_type(right):
        return False
    if policy_provider_authority(left, docs) != policy_provider_authority(right, docs):
        return False
    if normalized_policy_name(left.name) != normalized_policy_name(right.name):
        return False
    left_years, right_years = _program_years(left, docs), _program_years(right, docs)
    if left_years and right_years and left_years != right_years:
        return False
    left_regions = canonical_region_ids(left.region_codes)
    right_regions = canonical_region_ids(right.region_codes)
    if left_regions and right_regions and left_regions != right_regions:
        return False
    left_purpose, right_purpose = _purpose_signature(left.purpose), _purpose_signature(right.purpose)
    if left_purpose and right_purpose and left_purpose != right_purpose:
        return False
    for left_values, right_values in (
        (_normalized_values(left.industry_inclusions_raw), _normalized_values(right.industry_inclusions_raw)),
        (_normalized_values(left.industry_exclusions_raw), _normalized_values(right.industry_exclusions_raw)),
    ):
        if left_values and right_values and left_values != right_values:
            return False
    if _status_class(left) != "UNKNOWN" and _status_class(right) != "UNKNOWN" and _status_class(left) != _status_class(right):
        return False
    for left_value, right_value in (
        (left.application_start, right.application_start),
        (left.application_end, right.application_end),
        (left.limit_krw, right.limit_krw),
        (left.interest_terms.annual_rate_percent, right.interest_terms.annual_rate_percent),
        (left.interest_terms.rate_discount_percentage_points, right.interest_terms.rate_discount_percentage_points),
        (left.guarantee_terms.coverage_ratio, right.guarantee_terms.coverage_ratio),
        (left.guarantee_terms.guarantee_fee_percent, right.guarantee_terms.guarantee_fee_percent),
        (left.repayment_terms.principal_grace_months, right.repayment_terms.principal_grace_months),
        (left.repayment_terms.maturity_months, right.repayment_terms.maturity_months),
    ):
        if not _compatible_optional(left_value, right_value):
            return False
    shared_conditions = set(_eligibility_map(left)).intersection(_eligibility_map(right))
    if any(_eligibility_map(left)[key] != _eligibility_map(right)[key] for key in shared_conditions):
        return False
    return True


def policy_program_years(
    policy: PolicyCandidate,
    documents: dict[str, SourceDocument] | None = None,
) -> tuple[str, ...]:
    return _program_years(policy, documents or {})


def material_policy_conflicts(
    left: PolicyCandidate,
    right: PolicyCandidate,
    documents: dict[str, SourceDocument] | None = None,
) -> list[str]:
    """Return material fields that prohibit merging otherwise equivalent programs."""
    docs = documents or {}
    if normalized_policy_name(left.name) != normalized_policy_name(right.name):
        return []
    if policy_provider_authority(left, docs) != policy_provider_authority(right, docs):
        return []
    conflicts: list[str] = []
    if _policy_type(left) != _policy_type(right):
        conflicts.append("policy_type")
    left_years, right_years = _program_years(left, docs), _program_years(right, docs)
    if left_years and right_years and left_years != right_years:
        conflicts.append("program_year")
    left_regions, right_regions = canonical_region_ids(left.region_codes), canonical_region_ids(right.region_codes)
    if left_regions and right_regions and left_regions != right_regions:
        conflicts.append("region")
    if _status_class(left) != "UNKNOWN" and _status_class(right) != "UNKNOWN" and _status_class(left) != _status_class(right):
        conflicts.append("application_status")
    for field_name, left_value, right_value in (
        ("application_start", left.application_start, right.application_start),
        ("application_end", left.application_end, right.application_end),
        ("limit_krw", left.limit_krw, right.limit_krw),
        ("interest_terms.annual_rate_percent", left.interest_terms.annual_rate_percent, right.interest_terms.annual_rate_percent),
        ("interest_terms.rate_discount_percentage_points", left.interest_terms.rate_discount_percentage_points, right.interest_terms.rate_discount_percentage_points),
        ("guarantee_terms.coverage_ratio", left.guarantee_terms.coverage_ratio, right.guarantee_terms.coverage_ratio),
        ("guarantee_terms.guarantee_fee_percent", left.guarantee_terms.guarantee_fee_percent, right.guarantee_terms.guarantee_fee_percent),
        ("repayment_terms.principal_grace_months", left.repayment_terms.principal_grace_months, right.repayment_terms.principal_grace_months),
        ("repayment_terms.maturity_months", left.repayment_terms.maturity_months, right.repayment_terms.maturity_months),
    ):
        if not _compatible_optional(left_value, right_value):
            conflicts.append(field_name)
    left_conditions, right_conditions = _eligibility_map(left), _eligibility_map(right)
    shared_conditions = set(left_conditions).intersection(right_conditions)
    if any(left_conditions[key] != right_conditions[key] for key in shared_conditions):
        conflicts.append("eligible_business_category")
    left_industries = _normalized_values(left.industry_inclusions_raw)
    right_industries = _normalized_values(right.industry_inclusions_raw)
    if left_industries and right_industries and left_industries != right_industries:
        conflicts.append("eligible_business_category")
    return sorted(set(conflicts))
def semantic_policy_merge_fingerprint(
    policies: list[PolicyCandidate],
    documents: dict[str, SourceDocument] | None = None,
) -> str:
    docs = documents or {}

    def populated(values: Iterable[object]) -> str:
        return ",".join(sorted({str(value) for value in values if value not in {None, ""}}))

    material = "|".join((
        populated(policy_provider_authority(item, docs) for item in policies),
        populated(normalized_policy_name(item.name) for item in policies),
        populated(_policy_type(item) for item in policies),
        populated(year for item in policies for year in _program_years(item, docs)),
        populated(region for item in policies for region in canonical_region_ids(item.region_codes)),
        populated(purpose for item in policies for purpose in _purpose_signature(item.purpose)),
        populated(value for item in policies for value in _normalized_values(item.industry_inclusions_raw)),
        populated(value for item in policies for value in _normalized_values(item.industry_exclusions_raw)),
        populated(_status_class(item) for item in policies),
        populated(item.application_start for item in policies),
        populated(item.application_end for item in policies),
        populated(item.limit_krw for item in policies),
        populated(item.interest_terms.annual_rate_percent for item in policies),
        populated(item.interest_terms.rate_discount_percentage_points for item in policies),
        populated(item.guarantee_terms.coverage_ratio for item in policies),
        populated(item.guarantee_terms.guarantee_fee_percent for item in policies),
        populated(item.guarantee_terms.collateral_required for item in policies),
        populated(item.repayment_terms.principal_grace_months for item in policies),
        populated(item.repayment_terms.maturity_months for item in policies),
        populated(_normalized(item.repayment_terms.repayment_method or "") for item in policies),
        populated(
            f"{key}:{operator}:{value}"
            for item in policies
            for key, (operator, value) in _eligibility_map(item).items()
        ),
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def canonicalize_policy_identity(
    policy: PolicyCandidate,
    documents: dict[str, SourceDocument],
) -> PolicyCandidate:
    """Keep the extractor ID for audit while using a deterministic primary key."""
    fingerprint = policy_identity_fingerprint(policy, documents)
    return policy.model_copy(update={
        "extractor_policy_candidate_id": policy.extractor_policy_candidate_id or policy.policy_candidate_id,
        "identity_fingerprint": fingerprint,
        "policy_candidate_id": "POL-" + fingerprint[:24].upper(),
    })
