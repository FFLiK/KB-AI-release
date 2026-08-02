"""Deterministic numeric and unit normalization for extracted official facts."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class NormalizedNumericUnit:
    raw_value: str
    normalized_value: Decimal
    normalized_unit: str
    rule_id: str = "NUMERIC_UNIT_CANONICAL_V1"


_UNIT_ALIASES = {
    "%": "PERCENT", "percent": "PERCENT", "percentage": "PERCENT", "\ud37c\uc13c\ud2b8": "PERCENT",
    "%p": "PERCENTAGE_POINT", "percentage point": "PERCENTAGE_POINT", "percentage points": "PERCENTAGE_POINT",
    "\uc6d0": "KRW", "\ub9cc\uc6d0": "KRW", "\ubc31\ub9cc\uc6d0": "KRW", "\uc5b5\uc6d0": "KRW",
    "krw": "KRW", "krw/usd": "KRW_PER_USD", "days": "DAYS", "months": "MONTHS",
    "month": "MONTHS", "\uac1c\uc6d4": "MONTHS", "\ub2ec": "MONTHS",
    "year": "YEARS", "years": "YEARS", "\ub144": "YEARS",
}
_CURRENCY_MULTIPLIERS = {"\uc6d0": Decimal("1"), "\ub9cc\uc6d0": Decimal("10000"), "\ubc31\ub9cc\uc6d0": Decimal("1000000"), "\uc5b5\uc6d0": Decimal("100000000")}
_NUMBER_RE = re.compile(
    r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>"
    r"%\s*[pP]?|percentage\s+points?|percent(?:age)?|\ud37c\uc13c\ud2b8"
    r"|\ubc31\ub9cc\uc6d0|\ub9cc\uc6d0|\uc5b5\uc6d0|\uc6d0|KRW(?:/USD)?"
    r"|months?|\uac1c\uc6d4|\ub2ec|years?|\ub144|days?"
    r")?",
    re.IGNORECASE,
)


def _canonical_unit(value: object | None) -> str | None:
    if value is None:
        return None
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()
    text = re.sub(r"\s+", " ", text).replace("% p", "%p")
    return _UNIT_ALIASES.get(text)


def normalize_numeric_unit(raw_value: object, raw_unit: object | None = None) -> NormalizedNumericUnit:
    """Return a Decimal and canonical unit without changing the source evidence."""
    raw = unicodedata.normalize("NFKC", str(raw_value or "")).strip()
    match = _NUMBER_RE.fullmatch(raw.replace(",", ""))
    if not match:
        raise ValueError(f"unparseable numeric value: {raw_value!r}")
    try:
        value = Decimal(match.group("value"))
    except InvalidOperation as exc:
        raise ValueError(f"unparseable numeric value: {raw_value!r}") from exc
    if not value.is_finite():
        raise ValueError("numeric value must be finite")
    raw_matched_unit = re.sub(r"\s+", "", match.group("unit") or "")
    unit = _canonical_unit(raw_matched_unit) or _canonical_unit(raw_unit)
    if unit is None:
        raise ValueError("numeric unit is ambiguous")
    multiplier = _CURRENCY_MULTIPLIERS.get(raw_matched_unit)
    if multiplier is not None:
        value *= multiplier
    return NormalizedNumericUnit(raw, value, unit)
