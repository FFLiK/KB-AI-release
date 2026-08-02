"""Canonical aliases for official event indicators and units."""
from __future__ import annotations

import re
import unicodedata


def _key(value: object | None) -> str:
    return re.sub(r"[\s_\-]+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


_INDICATOR_ALIASES = {
    "baserate": "BASE_RATE",
    "\uae30\uc900\uae08\ub9ac": "BASE_RATE",
    "\ud55c\uad6d\uc740\ud589\uae30\uc900\uae08\ub9ac": "BASE_RATE",
    "bokbaserate": "BASE_RATE",
}
_UNIT_ALIASES = {
    "%": "PERCENT",
    "percent": "PERCENT",
    "percentage": "PERCENT",
    "\ud37c\uc13c\ud2b8": "PERCENT",
}


def normalize_official_indicator(value: object | None) -> str | None:
    key = _key(value)
    if not key:
        return None
    return _INDICATOR_ALIASES.get(key, str(value).strip().upper())


def normalize_official_unit(value: object | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return _UNIT_ALIASES.get(_key(raw), raw.upper())
