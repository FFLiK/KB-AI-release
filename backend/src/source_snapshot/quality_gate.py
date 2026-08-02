from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timezone
from enum import Enum
from urllib.parse import urlsplit

from src.contracts.source_document import DocumentPageType, SourceDocument, SourceType
from src.source_snapshot.local_classification import LocalPageClassification, classify_local_page

_NAVIGATION_WORDS = {
    "메뉴", "홈", "로그인", "검색", "전체메뉴", "사이트맵", "이전", "다음",
    "목록", "바로가기", "개인정보처리방침", "copyright", "menu", "login",
}
_LIST_MARKERS = ("목록", "검색 결과", "게시판", "전체보기", "list", "search")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_DATE_RE = re.compile(r"(?:20\d{2}[./년-]\s*\d{1,2}|20\d{2})")



class SourceDisposition(str, Enum):
    REJECT = "REJECT"
    EXTRACT = "EXTRACT"
    TRAVERSE_LIST = "TRAVERSE_LIST"
    ROUTE_TO_DETAIL = "ROUTE_TO_DETAIL"
    FETCH_ATTACHMENTS = "FETCH_ATTACHMENTS"
    EXTRACT_AND_TRAVERSE = "EXTRACT_AND_TRAVERSE"
    RESOLVE_DYNAMIC_SOURCE = "RESOLVE_DYNAMIC_SOURCE"
    LOW_PRIORITY_EXTRACT = "LOW_PRIORITY_EXTRACT"
    REFERENCE_ONLY = "REFERENCE_ONLY"


@dataclass(frozen=True)
class SourceQualityAssessment:
    usable: bool
    reason_codes: list[str] = field(default_factory=list)
    disposition: SourceDisposition = SourceDisposition.REJECT
    body_characters: int = 0
    quality_score: float = 0.0
    routing_reasons: list[str] = field(default_factory=list)
    hard_rejection_reasons: list[str] = field(default_factory=list)
    priority: int = 0
    navigation_ratio: float = 0.0
    query_term_matches: int = 0
    final_url_specific: bool = True
    truncated: bool = False
    extraction_body: str = ""
    page_type: DocumentPageType = DocumentPageType.UNKNOWN
    classification_reasons: list[str] = field(default_factory=list)
    traversable: bool = False
    has_detail_links: bool = False
    has_attachments: bool = False
    substantive_content: bool = False


def _navigation_ratio(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 1.0
    navigation = content = 0
    for line in lines:
        lowered = line.lower()
        menu_like = any(word in lowered for word in _NAVIGATION_WORDS)
        sentence_like = bool(re.search(r"[.!?\u3002]$", line)) or len(line) >= 80
        structured_signal = bool(_DATE_RE.search(line)) or bool(re.search(r"(?:\uc2dc|\uad70|\uad6c|\ub3d9|\ud589\uc0ac|\ucd95\uc81c|\uacf5\uc0ac|\uacf5\uace0)", line))
        if menu_like and not sentence_like:
            navigation += 1
        elif sentence_like or structured_signal:
            content += 1
    return navigation / max(1, navigation + content)


def _query_matches(query: str | None, text: str) -> int:
    if not query:
        return 1
    ignored = {"site", "공식", "공지", "발표", "전망", "현재", "최신"}
    terms = {
        token.lower() for token in _TOKEN_RE.findall(query)
        if token.lower() not in ignored and not token.lower().endswith("go")
    }
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def assess_source_quality(
    document: SourceDocument,
    *,
    query: str | None,
    as_of_date: date,
    max_input_characters: int = 30_000,
    agent_type: object | None = None,
) -> SourceQualityAssessment:
    body = document.body_text.strip()
    reasons: list[str] = []
    is_local_agent = str(agent_type).split(".")[-1] == "LOCAL_EVENT"
    is_trusted_official = str(document.source_trust_level).split(".")[-1] == "OFFICIAL_TRUSTED" or document.source_type in {SourceType.OFFICIAL_PRIMARY, SourceType.OFFICIAL_LOCAL_GOV}
    local_classification: LocalPageClassification | None = classify_local_page(document) if (
        is_local_agent and is_trusted_official
    ) else None
    ratio = _navigation_ratio(body)
    matches = _query_matches(query, f"{document.title}\n{body[:12_000]}")
    path = urlsplit(document.canonical_url).path.strip("/")
    title_lower = document.title.lower()
    specific = bool(path and path not in {"index.do", "main.do", "index.html"}) and not any(
        marker in title_lower for marker in _LIST_MARKERS
    )

    if len(body) < 80:
        reasons.append("INSUFFICIENT_CONTENT")
    if ratio >= 0.66:
        reasons.append("NAVIGATION_ONLY")
    if query and matches == 0:
        reasons.append("QUERY_IRRELEVANT")
    if not specific and len(body) < 2_000:
        reasons.append("NAVIGATION_OR_LIST_PAGE")
    if local_classification:
        reasons.extend(local_classification.reason_codes)
        if local_classification.is_traversable:
            # A structured official list is a routing document, not generic
            # navigation. It is retained for bounded detail traversal and,
            # only when rows are sufficient, row-bounded extraction.
            reasons = [
                reason for reason in reasons
                if reason not in {
                    "INSUFFICIENT_CONTENT", "NAVIGATION_ONLY",
                    "QUERY_IRRELEVANT", "NAVIGATION_OR_LIST_PAGE",
                }
            ]
    if document.published_at:
        published = document.published_at
        if published.tzinfo is not None:
            published = published.astimezone(timezone.utc).replace(tzinfo=None)
        if (as_of_date - published.date()).days > 550:
            reasons.append("STALE_SOURCE")
    if not is_trusted_official:
        reasons.append("UNVERIFIED_SOURCE_TIER")
    substantive = (
        len(body) >= 80 and ratio < 0.66
        and "NAVIGATION_OR_LIST_PAGE" not in reasons
    )

    hard_rejection_reasons = []
    if not body:
        hard_rejection_reasons.append("EMPTY_EXTRACTION")
    if document.security_flags:
        hard_rejection_reasons.append("SECURITY_POLICY_VIOLATION")
    if hard_rejection_reasons:
        disposition = SourceDisposition.REJECT
    elif local_classification and local_classification.is_traversable:
        disposition = SourceDisposition.TRAVERSE_LIST
    elif document.detail_urls:
        disposition = (
            SourceDisposition.EXTRACT_AND_TRAVERSE
            if substantive else SourceDisposition.ROUTE_TO_DETAIL
        )
    elif document.attachment_urls:
        disposition = (
            SourceDisposition.EXTRACT_AND_TRAVERSE
            if substantive else SourceDisposition.FETCH_ATTACHMENTS
        )
    elif "topis" in document.canonical_url.casefold():
        disposition = SourceDisposition.RESOLVE_DYNAMIC_SOURCE
    elif "UNVERIFIED_SOURCE_TIER" in reasons:
        disposition = SourceDisposition.LOW_PRIORITY_EXTRACT
    elif ("NAVIGATION_ONLY" in reasons or "NAVIGATION_OR_LIST_PAGE" in reasons) and (local_classification is None or local_classification.page_type not in {DocumentPageType.EVENT_DETAIL_PAGE, DocumentPageType.LOCAL_NOTICE_DETAIL, DocumentPageType.EVENT_ATTACHMENT}):
        disposition = SourceDisposition.REFERENCE_ONLY
    elif any(reason in reasons for reason in {"QUERY_IRRELEVANT", "STALE_SOURCE", "INSUFFICIENT_CONTENT"}):
        disposition = SourceDisposition.LOW_PRIORITY_EXTRACT
    else:
        disposition = SourceDisposition.EXTRACT
    usable = disposition in {
        SourceDisposition.EXTRACT,
        SourceDisposition.EXTRACT_AND_TRAVERSE,
    }
    truncated = usable and len(body) > max_input_characters
    extraction_body = body[:max_input_characters] if truncated else body
    if truncated:
        reasons.append("INPUT_TRUNCATED")
    return SourceQualityAssessment(
        usable=usable,
        disposition=disposition,
        quality_score=float(max(0, 100 - int(ratio * 40) - (25 if "UNVERIFIED_SOURCE_TIER" in reasons else 0))),
        routing_reasons=list(reasons),
        hard_rejection_reasons=hard_rejection_reasons,
        priority=100 if disposition == SourceDisposition.EXTRACT else (70 if disposition == SourceDisposition.LOW_PRIORITY_EXTRACT else 40),
        reason_codes=reasons,
        body_characters=len(body),
        navigation_ratio=ratio,
        query_term_matches=matches,
        final_url_specific=specific,
        truncated=truncated,
        extraction_body=extraction_body,
        page_type=local_classification.page_type if local_classification else document.page_type,
        classification_reasons=local_classification.reason_codes if local_classification else document.classification_reasons,
        traversable=bool(local_classification and local_classification.is_traversable),
        has_detail_links=bool(document.detail_urls),
        has_attachments=bool(document.attachment_urls),
        substantive_content=substantive,
    )
