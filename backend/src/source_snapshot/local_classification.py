"""Deterministic classification for local-government pages and event listings."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.contracts.source_document import DocumentPageType, SourceDocument

_DATE_RE = re.compile(
    r"(?:20\d{2}|['\u2018\u2019]?\d{2})\s*[./\-\ub144]\s*\d{1,2}\s*[./\-\uc6d4]\s*\d{1,2}|\d{1,2}\s*\uc6d4\s*\d{1,2}\s*\uc77c"
)
_LOCATION_RE = re.compile(
    r"(?:\b(?:venue|location|place|hall|park|station|road|street|square)\b|[\uac00-\ud7a3]+(?:\ud2b9\ubcc4\uc2dc|\uad11\uc5ed\uc2dc|\uc2dc|\uad70|\uad6c|\ub3d9|\ub85c|\uae38|\uad11\uc7a5|\uacf5\uc6d0|\uc5ed|\uc13c\ud130))",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"(?:\b(?:open|ongoing|scheduled|closed|registration|notice|event|festival|construction|closure)\b|\uc9c4\ud589|\uc608\uc815|\uc811\uc218|\uacf5\uc0ac|\ud1b5\uc81c|\ud589\uc0ac|\ucd95\uc81c|\uacf5\uace0)",
    re.IGNORECASE,
)
_LIST_RE = re.compile(r"(?:\b(?:list|board|search)\b|\ubaa9\ub85d|\uac8c\uc2dc\ud310|\uac80\uc0c9\uacb0\uacfc)", re.IGNORECASE)
_NOTICE_RE = re.compile(r"(?:\b(?:notice|board)\b|\uacf5\uace0|\uc54c\ub9bc|\uac8c\uc2dc)", re.IGNORECASE)
_DETAIL_PATH_RE = re.compile(r"(?:view\.do|detail|board|notice|event|festival)", re.IGNORECASE)
_ATTACHMENT_RE = re.compile(r"\.(?:pdf|hwp|hwpx|txt)(?:$|[?#])", re.IGNORECASE)


@dataclass(frozen=True)
class LocalPageClassification:
    page_type: DocumentPageType
    reason_codes: list[str]
    is_traversable: bool = False
    has_row_bounded_evidence: bool = False


def _is_local(document: SourceDocument) -> bool:
    return str(document.source_type).split(".")[-1] == "OFFICIAL_LOCAL_GOV"


def classify_local_page(document: SourceDocument) -> LocalPageClassification:
    """Classify a local page without using a search-result snippet as evidence."""
    text = "\n".join([document.title, document.body_text]).strip()
    path = urlsplit(document.canonical_url).path.casefold()
    reasons: list[str] = []
    if not text:
        return LocalPageClassification(DocumentPageType.UNUSABLE_CONTENT, ["EMPTY_BODY"])
    if document.parent_source_id and (
        _ATTACHMENT_RE.search(path) or "pdf" in (document.content_type or "").casefold()
    ):
        return LocalPageClassification(DocumentPageType.EVENT_ATTACHMENT, ["ATTACHMENT_CONTENT"])

    evidence = {
        "TITLE": bool(document.title.strip()),
        "DATE": bool(_DATE_RE.search(text)),
        "LOCATION": bool(_LOCATION_RE.search(text)),
        "STATUS": bool(_STATUS_RE.search(text)),
        "DETAIL_LINK": bool(document.detail_urls),
        "OFFICIAL_ORGANIZER": _is_local(document),
    }
    reasons.extend(f"LOCAL_CLASSIFICATION_{name}" for name, present in evidence.items() if present)
    score = sum(evidence.values())
    event_evidence = evidence["DATE"] or evidence["LOCATION"] or evidence["STATUS"] or evidence["DETAIL_LINK"]
    row_evidence = [
        row for row in document.structured_event_rows
        if _DATE_RE.search(row.text) and _LOCATION_RE.search(row.text)
    ]
    list_like = (
        len(document.detail_urls) >= 2
        or len(document.structured_event_rows) >= 2
        or bool(_LIST_RE.search(path))
        or bool(_LIST_RE.search(document.title))
    )
    notice_like = bool(_NOTICE_RE.search(path)) or bool(_NOTICE_RE.search(document.title))
    if list_like and not (document.parent_source_id or "view.do" in path or "detail" in path) and score >= 2 and event_evidence:
        page_type = DocumentPageType.LOCAL_NOTICE_LIST if notice_like else DocumentPageType.STRUCTURED_EVENT_LIST
        reasons.append("LOCAL_STRUCTURED_LIST_QUALIFIED")
        return LocalPageClassification(page_type, reasons, True, bool(row_evidence))
    if _DETAIL_PATH_RE.search(path) or document.parent_source_id:
        page_type = DocumentPageType.LOCAL_NOTICE_DETAIL if notice_like else DocumentPageType.EVENT_DETAIL_PAGE
        return LocalPageClassification(page_type, reasons or ["LOCAL_DETAIL_URL_PATTERN"])
    if document.detail_urls or document.attachment_urls:
        page_type = DocumentPageType.LOCAL_NOTICE_LIST if notice_like else DocumentPageType.STRUCTURED_EVENT_LIST
        return LocalPageClassification(
            page_type,
            [*reasons, "LOCAL_ROUTING_LINKS_DISCOVERED"],
            True,
            bool(row_evidence),
        )
    if score >= 2 and event_evidence and (document.detail_urls or row_evidence):
        return LocalPageClassification(
            DocumentPageType.STRUCTURED_EVENT_LIST,
            [*reasons, "LOCAL_STRUCTURED_LIST_QUALIFIED"],
            True,
            bool(row_evidence),
        )
    if _is_local(document) and (score < 2 or not event_evidence):
        return LocalPageClassification(DocumentPageType.NAVIGATION_ONLY, reasons or ["LOCAL_NAVIGATION_NO_EVENT_EVIDENCE"])
    return LocalPageClassification(DocumentPageType.UNKNOWN, reasons)
