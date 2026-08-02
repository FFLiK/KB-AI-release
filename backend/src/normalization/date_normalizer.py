from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.contracts.source_document import SourceDocument


class DateNormalizationError(ValueError): pass


@dataclass(frozen=True)
class MonthYearAnchor:
    year: int
    source: str
    text: str
    start_offset: int
    end_offset: int


_ENGLISH_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
_REPORT_CONTEXT = re.compile(r"report(?:ing)?\s+period|fiscal\s+year|\bfy\b|report|\ubcf4\uace0\uc11c|\uae30\uc900\ub144\ub3c4", re.IGNORECASE)
_PUBLISHED_CONTEXT = re.compile(r"published|publication date|\uac8c\uc7ac\uc77c|\ubc1c\ud589\uc77c|\uc791\uc131\uc77c", re.IGNORECASE)


def normalize_date(raw: str | None, published_at: date | None, title: str | None = None) -> tuple[date | None, str]:
    if not raw: return None, "KO_DATE_EMPTY_V1"
    value = raw.strip().lstrip("'\u2018\u2019")
    try: return date.fromisoformat(value[:10]), "ISO_DATE_V1"
    except ValueError: pass
    match = re.search(r"(?:(['\u2018\u2019]?\d{2,4})\s*[\ub144./-]\s*)?(\d{1,2})\s*[\uc6d4./-]\s*(\d{1,2})\s*\uc77c?", value)
    if match:
        raw_year = match.group(1).lstrip("'\u2018\u2019") if match.group(1) else None
        year = int(raw_year) if raw_year else (published_at.year if published_at else None)
        if raw_year and len(raw_year) == 2: year += 2000
        if year is None: raise DateNormalizationError("year omitted without published_at")
        try: parsed = date(year, int(match.group(2)), int(match.group(3)))
        except ValueError as exc: raise DateNormalizationError(str(exc)) from exc
        return parsed, "KO_DATE_TWO_DIGIT_YEAR_V1" if raw_year and len(raw_year) == 2 else "KO_DATE_ABSOLUTE_V1" if raw_year else "KO_DATE_YEAR_FROM_PUBLISHED_AT_V1"
    if published_at:
        relative = {"\uc624\ub298": 0, "\uae08\uc77c": 0, "\ub0b4\uc77c": 1, "\uc775\uc77c": 1, "\uc5b4\uc81c": -1, "\uc804\uc77c": -1}
        for token, delta in relative.items():
            if token in value: return published_at + timedelta(days=delta), "KO_DATE_RELATIVE_PUBLISHED_AT_V1"
    raise DateNormalizationError(f"unparseable date: {raw}")


def _month_only(raw: str | None) -> tuple[int, str] | None:
    if not raw: return None
    value = raw.strip()
    english = re.fullmatch(r"([A-Za-z]+)\.?", value)
    if english and english.group(1).casefold() in _ENGLISH_MONTHS:
        return _ENGLISH_MONTHS[english.group(1).casefold()], english.group(1)
    korean = re.fullmatch(r"(\d{1,2})\s*\uc6d4", value)
    if korean and 1 <= int(korean.group(1)) <= 12:
        return int(korean.group(1)), korean.group(0)
    return None


def _year_anchor(text: str, *, source: str, context: re.Pattern[str]) -> MonthYearAnchor | None:
    for match in _YEAR.finditer(text):
        window = text[max(0, match.start() - 48):min(len(text), match.end() + 48)]
        if context.search(window):
            return MonthYearAnchor(int(match.group(1)), source, match.group(0), match.start(), match.end())
    return None


def normalize_document_anchored_month(raw: str | None, document: SourceDocument) -> tuple[date, str, MonthYearAnchor]:
    """Normalize a month only when the source itself supplies a verifiable year."""
    parsed = _month_only(raw)
    if not parsed:
        raise DateNormalizationError("not a month-only expression")
    month, _ = parsed
    header = document.body_text[:2500]
    anchors = (
        _year_anchor(document.title, source="DOCUMENT_TITLE_REPORT_PERIOD", context=_REPORT_CONTEXT),
        _year_anchor(header, source="DOCUMENT_HEADER_REPORT_PERIOD", context=_REPORT_CONTEXT),
        _year_anchor(header, source="DOCUMENT_BODY_PUBLICATION_DATE", context=_PUBLISHED_CONTEXT),
    )
    anchor = next((item for item in anchors if item is not None), None)
    if anchor is None and document.published_at and re.search(r"\b(19|20)\d{2}\b", document.published_at.isoformat()):
        year_text = str(document.published_at.year)
        anchor = MonthYearAnchor(year=document.published_at.year, source="SOURCE_DOCUMENT_PUBLISHED_AT", text=year_text, start_offset=0, end_offset=len(year_text))
    if anchor is None:
        raise DateNormalizationError("month-only expression has no source-anchored year")
    return date(anchor.year, month, 1), "DOCUMENT_ANCHORED_MONTH_YEAR_V1", anchor
