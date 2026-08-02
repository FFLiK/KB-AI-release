"""Deterministic Korean venue cleanup before external geocoding calls."""
from __future__ import annotations

import re
import unicodedata

from src.normalization.address_normalizer import normalize_korean_address
from src.normalization.region_normalizer import canonical_region_id, region_display_name


# Codes are intentionally mapped to names before querying a provider: codes are
# useful identifiers, but are not useful Korean search terms.
ADMINISTRATIVE_AREA_NAMES = {
    "11": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc",
    "11680": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uac15\ub0a8\uad6c",
    "11650": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc11c\ucd08\uad6c",
    "11710": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc1a1\ud30c\uad6c",
}

_GENERIC_TAIL = re.compile(
    r"\s*(?:\ubc0f\s*)?(?:\uc8fc\uc694\s*)?"
    r"(?:\uad00\uad11\uba85\uc18c|\ud589\uc0ac\uc7a5\uc18c|\uc8fc\uc694\uc7a5\uc18c|\uc77c\ub300)\s*$",
    re.IGNORECASE,
)
_SEPARATOR = re.compile(r"\s*(?:,|/|;|\u00b7|\ubc0f)\s*")
_VARIANTS = {
    "\ucf54\uc5d1\uc2a4\ubab0": "\ucf54\uc5d1\uc2a4",
    "\ucf54\uc5d1\uc2a4 \uc55e \ud2b9\uc124\ubb34\ub300": "\ucf54\uc5d1\uc2a4",
    "coex mall": "coex",
    "coex special stage": "coex",
}


def administrative_area_names(codes: list[str] | None) -> list[str]:
    """Return normalized provider-searchable administrative-area names."""
    result: list[str] = []
    for code in codes or []:
        raw = str(code)
        canonical = canonical_region_id(raw)
        normalized = canonical if canonical and re.fullmatch(r"(?:KR-)?\d+", raw, re.IGNORECASE) else normalize_korean_address(raw)
        if not normalized:
            continue
        result.append(ADMINISTRATIVE_AREA_NAMES.get(normalized.removeprefix("KR-"), region_display_name(normalized)))
    return list(dict.fromkeys(result))


def normalize_venue_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = " ".join(normalized.split())
    normalized = _GENERIC_TAIL.sub("", normalized).strip(" ,;/\u00b7")
    folded = normalized.casefold()
    for variant, replacement in _VARIANTS.items():
        if folded == variant.casefold():
            return replacement
    return normalized


def venue_search_forms(
    value: str,
    *,
    administrative_area_codes: list[str] | None = None,
    source_context: str | None = None,
) -> list[str]:
    """Generate deterministic full, landmark, district and context search forms."""
    cleaned = normalize_venue_text(value)
    areas = administrative_area_names(administrative_area_codes)
    context = normalize_venue_text(source_context or "")
    pieces = [normalize_venue_text(item) for item in _SEPARATOR.split(cleaned) if item.strip()]
    core = pieces[0] if pieces else cleaned
    forms: list[str] = [cleaned, core]
    if re.search(r"[\uac00-\ud7a3]", core) or "coex" in core.casefold():
        for area in areas:
            forms.append(f"{core} {area}")
    if context:
        # Keep this short so it remains a location query rather than replaying
        # an entire untrusted source into the provider request.
        forms.append(f"{core} {context[:80]}")
    return list(dict.fromkeys(item for item in forms if item))
