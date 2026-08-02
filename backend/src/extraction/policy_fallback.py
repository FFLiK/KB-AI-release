"""Strict, document-only fallback for official policy extraction failures."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import (
    EligibilityCondition,
    InterestTerms,
    PolicyCandidate,
    PolicyType,
    RepaymentTerms,
)
from src.contracts.source_document import SourceDocument, SourceTrustLevel, SourceType


_OFFICIAL_SOURCE_TYPES = {
    SourceType.OFFICIAL_PRIMARY,
    SourceType.OFFICIAL_SECONDARY,
    SourceType.OFFICIAL_LOCAL_GOV,
}
_POLICY_TYPE_PATTERNS = (
    (PolicyType.CREDIT_GUARANTEE, re.compile(r"credit[- ]?guarantee|\uc2e0\uc6a9\ubcf4\uc99d", re.IGNORECASE)),
    (PolicyType.INTEREST_SUBSIDY, re.compile(
        r"interest (?:rate )?(?:subsidy|support)|loan interest|\ub300\ucd9c\uc774\uc790|\uc774\ucc28\ubcf4\uc804|\uc774\uc790\uc9c0\uc6d0",
        re.IGNORECASE,
    )),
    (PolicyType.LOAN_SUPPORT, re.compile(
        r"loan (?:support|program)|working capital loan|\ub300\ucd9c\uc9c0\uc6d0|\uc735\uc790",
        re.IGNORECASE,
    )),
)
_DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})[-./](\d{1,2})[-./](\d{1,2})\b"),
    re.compile(r"\b(20\d{2})\ub144\s*(\d{1,2})\uc6d4\s*(\d{1,2})\uc77c"),
)


def is_official_trusted_source(document: SourceDocument) -> bool:
    """Allow repair/fallback only for an already trusted official document."""
    return (
        document.source_type in _OFFICIAL_SOURCE_TYPES
        and document.source_trust_level == SourceTrustLevel.OFFICIAL_TRUSTED
    )


def _dates(text: str) -> list[date]:
    values: list[date] = []
    for pattern in _DATE_PATTERNS:
        for year, month, day in pattern.findall(text):
            try:
                value = date(int(year), int(month), int(day))
            except ValueError:
                continue
            if value not in values:
                values.append(value)
    return values


def _decimal(match: re.Match[str]) -> Decimal | None:
    try:
        return Decimal(match.group(1).replace(",", ""))
    except (InvalidOperation, IndexError):
        return None


def _limit_krw(text: str) -> Decimal | None:
    match = re.search(
        r"(?:up to|maximum|limit|\ucd5c\ub300|\ud55c\ub3c4)\s*(?:KRW\s*)?([\d,]+(?:\.\d+)?)\s*(KRW|\uc5b5\uc6d0|\ubc31\ub9cc\uc6d0|\ub9cc\uc6d0|\uc6d0)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = _decimal(match)
    if value is None:
        return None
    unit = match.group(2).casefold()
    multiplier = {
        "krw": Decimal("1"), "\uc6d0": Decimal("1"), "\ub9cc\uc6d0": Decimal("10000"),
        "\ubc31\ub9cc\uc6d0": Decimal("1000000"), "\uc5b5\uc6d0": Decimal("100000000"),
    }.get(unit)
    return value * multiplier if multiplier is not None else None


def _interest_terms(text: str) -> InterestTerms:
    discount = re.search(
        r"([\d.]+)\s*(?:%p|percentage\s*points?|\ud37c\uc13c\ud2b8\s*\ud3ec\uc778\ud2b8)",
        text,
        re.IGNORECASE,
    )
    if discount:
        value = _decimal(discount)
        return InterestTerms(rate_discount_percentage_points=value)
    rate = re.search(
        r"(?:interest\s*rate|rate|\uae08\ub9ac)\D{0,20}([\d.]+)\s*%",
        text,
        re.IGNORECASE,
    )
    return InterestTerms(annual_rate_percent=_decimal(rate)) if rate else InterestTerms()


def _repayment_terms(text: str) -> RepaymentTerms:
    match = re.search(
        r"(?:repayment|maturity|grace|\uc0c1\ud658|\uac70\uce58)\D{0,20}(\d+)\s*(months?|\uac1c\uc6d4|years?|\ub144)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return RepaymentTerms()
    months = int(match.group(1)) * (12 if match.group(2).casefold() in {"year", "years", "\ub144"} else 1)
    if re.search(r"grace|\uac70\uce58", match.group(0), re.IGNORECASE):
        return RepaymentTerms(principal_grace_months=months)
    return RepaymentTerms(maturity_months=months)


def _policy_name(document: SourceDocument, text: str, policy_type: PolicyType) -> str | None:
    title = document.title.strip()
    if title and any(pattern.search(title) for kind, pattern in _POLICY_TYPE_PATTERNS if kind == policy_type):
        return title
    match = re.search(
        r"(?:program|policy|project|\uc0ac\uc5c5\uba85|\uc9c0\uc6d0\uc0ac\uc5c5)\s*[:\uff1a]\s*([^\n]{2,160})",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" .")
    for line in text.splitlines():
        compact = line.strip()
        if len(compact) >= 3 and any(pattern.search(compact) for kind, pattern in _POLICY_TYPE_PATTERNS if kind == policy_type):
            return compact[:160]
    return None


def _region_codes(text: str) -> list[str]:
    lowered = text.casefold()
    if "11680" in text or "gangnam-gu" in lowered or "gangnam gu" in lowered or "\uac15\ub0a8\uad6c" in text:
        return ["11680"]
    if re.search(r"(?:seoul|\uc11c\uc6b8\ud2b9\ubcc4\uc2dc|\uc11c\uc6b8\uc2dc)", text, re.IGNORECASE):
        return ["11"]
    return []


def _eligibility_conditions(text: str) -> list[EligibilityCondition]:
    match = re.search(
        r"(?:eligible(?:\s+(?:businesses|applicants))?|eligibility|\uc9c0\uc6d0\ub300\uc0c1|\uc2e0\uccad\ub300\uc0c1)\s*[:\uff1a]\s*([^\n.]{2,240})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return []
    value = match.group(1).strip()
    return [EligibilityCondition(
        field_path="explicit_eligibility", operator="CONTAINS", expected_value=value,
    )]


def deterministic_policy_fallback(
    document: SourceDocument,
    research_run_id: str,
) -> PolicyCandidate | None:
    """Recover only plainly stated policy facts from a trusted official source.

    This intentionally returns no candidate when a support type or program name is
    not directly present. It never derives availability, budgets, or effects.
    """
    if not is_official_trusted_source(document):
        return None
    text = document.body_text
    policy_type = next((kind for kind, pattern in _POLICY_TYPE_PATTERNS if pattern.search(text)), None)
    if policy_type is None:
        return None
    name = _policy_name(document, text, policy_type)
    if not name:
        return None
    dates = _dates(text)
    date_context = re.search(
        r"(?:application|apply|\uc2e0\uccad|\uc811\uc218).{0,180}", text, re.IGNORECASE | re.DOTALL)
    application_dates = _dates(date_context.group(0)) if date_context else []
    explicitly_closed = bool(re.search(r"applications? (?:are )?closed|\uc811\uc218\s*\ub9c8\uac10|\uc885\ub8cc", text, re.IGNORECASE))
    evidence = EvidenceRef(
        evidence_id="PFD-" + document.source_id,
        source_id=document.source_id,
        source_revision_id=document.revision_id,
        field_paths=[
            "name", "policy_type", "limit_krw", "interest_terms.annual_rate_percent",
            "interest_terms.rate_discount_percentage_points", "repayment_terms.principal_grace_months",
            "repayment_terms.maturity_months", "application_start", "application_end",
            "eligibility_conditions",
        ],
        quote=text,
        start_offset=0,
        end_offset=len(text),
    )
    host = urlsplit(document.canonical_url).hostname or "official authority"
    return PolicyCandidate(
        policy_candidate_id="POLICY-FALLBACK-PENDING",
        research_run_id=research_run_id,
        policy_type=policy_type,
        name=name,
        provider_raw=document.publisher or host,
        region_codes=_region_codes(f"{document.title}\n{text}"),
        limit_krw=_limit_krw(text),
        interest_terms=_interest_terms(text),
        repayment_terms=_repayment_terms(text),
        application_start=application_dates[0] if application_dates else None,
        application_end=application_dates[1] if len(application_dates) > 1 else None,
        application_status="CLOSED" if explicitly_closed else "STATUS_UNCONFIRMED",
        eligibility_conditions=_eligibility_conditions(text),
        source_ids=[document.source_id],
        evidence=[evidence],
        validation_notes=["POLICY_DETERMINISTIC_FALLBACK_USED"],
    )
