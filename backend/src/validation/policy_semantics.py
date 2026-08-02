"""Field-level, evidence-to-policy semantic validation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.contracts.policy_candidate import PolicyCandidate
from src.normalization.numeric_unit_normalizer import normalize_numeric_unit


_CLOSED = re.compile(r"\b(?:applications? (?:are )?closed|application closed|closed program)\b|\uc811\uc218\s*\ub9c8\uac10", re.IGNORECASE)
_EXHAUSTED = re.compile(r"\b(?:until funds? (?:are )?exhausted|budget exhausted)\b|\uc608\uc0b0\uc18c\uc9c4\uc2dc", re.IGNORECASE)
_NUMBER_TOKEN = re.compile(
    r"(?:KRW\s*)?[+-]?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:"
    r"%\s*[pP]?|percentage\s+points?|percent(?:age)?|\ud37c\uc13c\ud2b8"
    r"|\ubc31\ub9cc\uc6d0|\ub9cc\uc6d0|\uc5b5\uc6d0|\uc6d0|KRW(?:/USD)?"
    r"|months?|\uac1c\uc6d4|\ub2ec|years?|\ub144|days?"
    r")?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumericComparison:
    field_path: str
    expected_value: Decimal
    expected_unit: str
    quote: str
    normalized_value: Decimal | None = None
    normalized_unit: str | None = None
    matched: bool = False
    reason_code: str | None = None


@dataclass(frozen=True)
class PolicySemanticAssessment:
    failure_codes: list[str]
    explicitly_closed: bool
    numeric_comparisons: list[NumericComparison] = field(default_factory=list)


def _field_quotes(policy: PolicyCandidate, field_path: str) -> list[str]:
    return [
        evidence.quote for evidence in policy.evidence
        if any(path == field_path or path.startswith(f"{field_path}.") for path in evidence.field_paths)
    ]


def _canonical_value(value: Decimal | int, unit: str) -> Decimal:
    result = Decimal(str(value))
    return result * Decimal("12") if unit == "MONTHS" else result


def _numeric_match(
    value: Decimal | int,
    quotes: list[str],
    *,
    expected_unit: str,
    field_path: str,
) -> tuple[bool, list[NumericComparison], bool]:
    """Compare canonical value/unit pairs while keeping source text auditable."""
    expected = Decimal(str(value))
    comparisons: list[NumericComparison] = []
    saw_parseable = False
    for quote in quotes:
        quote_matched = False
        for token in _NUMBER_TOKEN.findall(quote):
            normalized_token = token
            if normalized_token.casefold().startswith("krw"):
                normalized_token = re.sub(r"^krw\s*", "", normalized_token, flags=re.IGNORECASE) + " KRW"
            try:
                normalized = normalize_numeric_unit(normalized_token)
            except ValueError:
                continue
            saw_parseable = True
            normalized_value = normalized.normalized_value
            normalized_unit = normalized.normalized_unit
            if expected_unit == "MONTHS" and normalized_unit == "YEARS":
                normalized_value *= Decimal("12")
                normalized_unit = "MONTHS"
            matched = normalized_unit == expected_unit and normalized_value == expected
            comparisons.append(NumericComparison(
                field_path=field_path,
                expected_value=expected,
                expected_unit=expected_unit,
                quote=quote,
                normalized_value=normalized_value,
                normalized_unit=normalized_unit,
                matched=matched,
                reason_code=None if matched else "POLICY_VALUE_OR_UNIT_MISMATCH",
            ))
            quote_matched = quote_matched or matched
        if quote_matched:
            return True, comparisons, saw_parseable
    return False, comparisons, saw_parseable


def _text_match(value: str, quotes: list[str]) -> bool:
    return any(value in quote for quote in quotes)


def assess_policy_semantics(policy: PolicyCandidate, as_of_date: date) -> PolicySemanticAssessment:
    """Return non-terminal semantic failures; evidence/source failures stay terminal elsewhere."""
    del as_of_date
    codes: list[str] = []
    comparisons: list[NumericComparison] = []
    all_quotes = [evidence.quote for evidence in policy.evidence]
    explicitly_closed = any(_CLOSED.search(quote) for quote in all_quotes)
    if any(_EXHAUSTED.search(quote) for quote in all_quotes) and policy.budget_status not in {
        "EXHAUSTED", "UNTIL_EXHAUSTED", "CLOSED",
    }:
        codes.append("POLICY_BUDGET_STATUS_MISMATCH")

    numeric_fields = [
        ("limit_krw", policy.limit_krw, "KRW", "POLICY_FIELD_VALUE_MISSING"),
        ("interest_terms.annual_rate_percent", policy.interest_terms.annual_rate_percent, "PERCENT", "POLICY_REQUIRED_TERM_MISSING"),
        ("interest_terms.rate_discount_percentage_points", policy.interest_terms.rate_discount_percentage_points, "PERCENTAGE_POINT", "POLICY_REQUIRED_TERM_MISSING"),
        ("repayment_terms.principal_grace_months", policy.repayment_terms.principal_grace_months, "MONTHS", "POLICY_REQUIRED_TERM_MISSING"),
        ("repayment_terms.maturity_months", policy.repayment_terms.maturity_months, "MONTHS", "POLICY_REQUIRED_TERM_MISSING"),
    ]
    for field_path, value, unit, missing_code in numeric_fields:
        quotes = _field_quotes(policy, field_path)
        if not quotes:
            continue
        if value is None:
            codes.append(missing_code)
            continue
        matched, field_comparisons, saw_parseable = _numeric_match(
            value, quotes, expected_unit=unit, field_path=field_path,
        )
        comparisons.extend(field_comparisons)
        if not matched:
            if not saw_parseable:
                codes.append("POLICY_NUMERIC_UNIT_AMBIGUOUS")
            else:
                # Keep the legacy aggregate code for API compatibility while
                # exposing the unit-aware reason to newer clients.
                codes.extend(["POLICY_FIELD_EVIDENCE_MISMATCH", "POLICY_FIELD_VALUE_OR_UNIT_MISMATCH"])

    collateral_quotes = _field_quotes(policy, "guarantee_terms.collateral_required")
    if collateral_quotes:
        collateral = policy.guarantee_terms.collateral_required
        if collateral is None:
            codes.append("POLICY_REQUIRED_TERM_MISSING")
        elif not _text_match("collateral", collateral_quotes):
            codes.append("POLICY_FIELD_EVIDENCE_MISMATCH")

    for field_path, value in (
        ("application_start", policy.application_start),
        ("application_end", policy.application_end),
    ):
        quotes = _field_quotes(policy, field_path)
        if not quotes:
            continue
        if value is None:
            codes.append("POLICY_APPLICATION_STATUS_UNRESOLVED")
        elif not _text_match(value.isoformat(), quotes):
            codes.append("POLICY_FIELD_EVIDENCE_MISMATCH")

    return PolicySemanticAssessment(sorted(set(codes)), explicitly_closed, comparisons)