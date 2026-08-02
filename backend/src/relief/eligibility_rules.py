"""Fail-closed declarative policy eligibility rules."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from src.contracts.store import StoreProfile
from src.normalization.region_normalizer import regions_match
from src.relief.policy_schema import PolicySchema

_ALLOWED_FIELDS = {
    "store_id",
    "business_type_code",
    "business_start_date",
    "annual_revenue_krw",
    "employee_count",
    "credit_band",
    "owner_age",
    "declared_monthly_revenue_krw",
    "business_age_months",
}
_ALLOWED_OPERATORS = {"EQ", "NE", "IN", "NOT_IN", "GE", "GT", "LE", "LT", "EXISTS"}

_BUSINESS_SIZE_TERMS = {
    "sme", "smes", "small business", "small businesses", "small_business",
    "micro business", "microenterprise", "\uc911\uc18c\uae30\uc5c5", "\uc18c\uc0c1\uacf5\uc778",
}


def _is_business_size_term(value: str) -> bool:
    normalized = " ".join(value.replace("_", " ").casefold().split())
    return normalized in _BUSINESS_SIZE_TERMS


def _condition_dimension(field_path: str) -> str:
    normalized = field_path.removeprefix("store_profile.").removeprefix("store.")
    return {
        "business_type_code": "INDUSTRY",
        "business_age_months": "REGISTRATION_AGE",
        "annual_revenue_krw": "REVENUE",
        "employee_count": "EMPLOYEE_COUNT",
        "credit_band": "CREDIT",
    }.get(normalized, "ENTITY_ATTRIBUTE")

def _business_age_months(start: str | None, as_of_date: date) -> int | None:
    if not start:
        return None
    opened = date.fromisoformat(start)
    return max(0, (as_of_date.year - opened.year) * 12 + as_of_date.month - opened.month)


def _actual_value(store: StoreProfile, field_path: str, as_of_date: date) -> Any:
    normalized = field_path.removeprefix("store_profile.").removeprefix("store.")
    if normalized not in _ALLOWED_FIELDS:
        raise ValueError(f"unsupported eligibility field: {field_path}")
    if normalized == "business_age_months":
        return _business_age_months(store.business_start_date, as_of_date)
    return getattr(store, normalized)


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    op = operator.upper()
    if op not in _ALLOWED_OPERATORS:
        raise ValueError(f"unsupported eligibility operator: {operator}")
    if op == "EXISTS":
        desired = True if expected is None else bool(expected)
        return (actual is not None) == desired
    if actual is None:
        return False
    if op in {"IN", "NOT_IN"}:
        values = expected if isinstance(expected, (list, tuple, set)) else [
            part.strip() for part in str(expected).split(",")
        ]
        matched = str(actual) in {str(value) for value in values}
        return matched if op == "IN" else not matched
    if isinstance(actual, Decimal):
        expected = Decimal(str(expected))
    elif isinstance(actual, int) and not isinstance(actual, bool):
        expected = int(expected)
    elif isinstance(actual, bool):
        expected = bool(expected)
    else:
        expected = str(expected)
        actual = str(actual)
    return {
        "EQ": actual == expected,
        "NE": actual != expected,
        "GE": actual >= expected,
        "GT": actual > expected,
        "LE": actual <= expected,
        "LT": actual < expected,
    }[op]


def evaluate_policy_eligibility_detailed(
    store_profile: StoreProfile,
    policy: PolicySchema,
    store_region_code: str = "11",
    as_of_date: date | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    analysis_date = as_of_date or date.today()
    logs: list[dict[str, Any]] = []
    if policy.budget_status == "CLOSED":
        return "CLOSED", "Application closed or budget exhausted", logs
    if policy.budget_status == "UNKNOWN":
        return "BUDGET_UNKNOWN", "Policy budget status unconfirmed", logs
    region_match = regions_match(store_region_code, policy.region_codes)
    if region_match is None:
        logs.append({"dimension": "REGION", "status": "UNKNOWN", "store_region": store_region_code, "policy_regions": policy.region_codes})
        return "NEEDS_INFORMATION", "Store or policy region could not be normalized", logs
    if not region_match:
        logs.append({"dimension": "REGION", "status": "FAILED", "store_region": store_region_code, "policy_regions": policy.region_codes})
        return "INELIGIBLE", f"Store region code '{store_region_code}' not matching policy regions", logs
    if policy.region_codes:
        logs.append({"dimension": "REGION", "status": "PASSED", "store_region": store_region_code, "policy_regions": policy.region_codes})
    industry_exclusions = [
        value for value in policy.industry_exclusions if not _is_business_size_term(value)
    ]
    industry_inclusions = [
        value for value in policy.industry_inclusions if not _is_business_size_term(value)
    ]
    for term in [*policy.industry_inclusions, *policy.industry_exclusions]:
        if _is_business_size_term(term):
            logs.append({
                "dimension": "BUSINESS_SIZE",
                "declared_term": term,
                "status": "DECLARED_NOT_COMPARED_TO_INDUSTRY",
            })
    if industry_exclusions and store_profile.business_type_code in industry_exclusions:
        return "INELIGIBLE", "Store business type is explicitly excluded", logs
    if industry_inclusions and store_profile.business_type_code not in industry_inclusions:
        return "INELIGIBLE", "Store business type is not in policy inclusions", logs

    for condition in policy.eligibility_conditions:
        entry = {
            "field_path": condition.field_path,
            "dimension": _condition_dimension(condition.field_path),
            "operator": condition.operator.upper(),
            "expected_value": condition.expected_value,
        }
        try:
            actual = _actual_value(store_profile, condition.field_path, analysis_date)
            entry["actual_value"] = actual
            if actual is None and condition.operator.upper() != "EXISTS":
                entry["status"] = "NEEDS_INFORMATION"
                logs.append(entry)
                return "NEEDS_INFORMATION", f"Missing required field: {condition.field_path}", logs
            passed = _compare(actual, condition.operator, condition.expected_value)
        except (ValueError, TypeError, ArithmeticError) as exc:
            entry["status"] = "INVALID_RULE"
            entry["detail"] = str(exc)
            logs.append(entry)
            return "NEEDS_INFORMATION", f"Eligibility rule could not be evaluated: {condition.field_path}", logs
        entry["status"] = "PASSED" if passed else "FAILED"
        logs.append(entry)
        if not passed:
            return "INELIGIBLE", f"Declared condition failed: {condition.field_path}", logs
    return "ELIGIBLE_ON_DECLARED_RULES", "All declared rules passed", logs


def evaluate_policy_eligibility(
    store_profile: StoreProfile,
    policy: PolicySchema,
    store_region_code: str = "11",
    as_of_date: date | None = None,
) -> tuple[str, str]:
    status, reason, _ = evaluate_policy_eligibility_detailed(
        store_profile, policy, store_region_code, as_of_date
    )
    return status, reason
