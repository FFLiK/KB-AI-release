"""Deterministic normalization used only for geocoding candidate comparison."""

from __future__ import annotations

import re
import unicodedata


_PROVINCE_ALIASES = {
    "서울": "서울특별시",
    "서울시": "서울특별시",
    "부산시": "부산광역시",
    "대구시": "대구광역시",
    "인천시": "인천광역시",
    "광주시": "광주광역시",
    "대전시": "대전광역시",
    "울산시": "울산광역시",
    "세종시": "세종특별자치시",
    "제주도": "제주특별자치도",
}


def normalize_korean_address(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    normalized = re.sub(r"[,;]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    if not normalized:
        return ""
    head, separator, tail = normalized.partition(" ")
    head = _PROVINCE_ALIASES.get(head, head)
    return head + (separator + tail if separator else "")
