"""Shared canonical administrative-region identifiers and matching rules."""
from __future__ import annotations

import re
import unicodedata

_REGION_ALIASES = {
    "11": "KR-11",
    "11680": "KR-11680",
    "kr-11680": "KR-11680",
    "11650": "KR-11650",
    "kr-11650": "KR-11650",
    "11710": "KR-11710",
    "kr-11710": "KR-11710",
    "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uac15\ub0a8\uad6c": "KR-11680",
    "\uc11c\uc6b8 \uac15\ub0a8\uad6c": "KR-11680",
    "\uac15\ub0a8\uad6c": "KR-11680",
    "seoul gangnam-gu": "KR-11680",
    "seoul gangnam gu": "KR-11680",
    "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc11c\ucd08\uad6c": "KR-11650",
    "\uc11c\uc6b8 \uc11c\ucd08\uad6c": "KR-11650",
    "\uc11c\ucd08\uad6c": "KR-11650",
    "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc1a1\ud30c\uad6c": "KR-11710",
    "\uc11c\uc6b8 \uc1a1\ud30c\uad6c": "KR-11710",
    "\uc1a1\ud30c\uad6c": "KR-11710",
}
_DISPLAY_NAMES = {
    "KR-11": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc",
    "KR-11680": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uac15\ub0a8\uad6c",
    "KR-11650": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc11c\ucd08\uad6c",
    "KR-11710": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc1a1\ud30c\uad6c",
}


def _key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
    return re.sub(r"\s+", " ", normalized)


def canonical_region_id(value: str | None) -> str | None:
    """Return a stable region code, or ``None`` when the value is unknown."""
    key = _key(value or "")
    if not key:
        return None
    if key in _REGION_ALIASES:
        return _REGION_ALIASES[key]
    numeric = re.fullmatch(r"(?:kr-)?(\d{2,10})", key)
    if numeric:
        return "KR-" + numeric.group(1)
    return None


def canonical_region_ids(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(
        region for value in values or [] if (region := canonical_region_id(value))
    ))


def region_display_name(value: str) -> str:
    if not value.upper().startswith("KR-"):
        return value
    return _DISPLAY_NAMES.get(canonical_region_id(value) or "", value)


def regions_match(store_region: str | None, policy_regions: list[str] | None) -> bool | None:
    """Return True/False, or None where either side cannot be safely compared."""
    if not policy_regions:
        return True
    store = canonical_region_id(store_region)
    declared = canonical_region_ids(policy_regions)
    if not store or not declared:
        return None
    if store in declared:
        return True
    # A broader region (for example KR-11) is eligible for a district within it.
    return any(store.startswith(region + "-") or region.startswith(store + "-") for region in declared)
