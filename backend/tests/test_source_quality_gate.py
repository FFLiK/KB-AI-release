from datetime import UTC, date, datetime
import hashlib

import httpx

from src.config.settings import Settings
from src.contracts.source_document import AccessStatus, SourceDocument, SourceType
from src.providers.base import SearchHit
from src.source_snapshot.fetcher import HttpDocumentFetcher
from src.source_snapshot.quality_gate import assess_source_quality


def source(body: str, *, title: str = "2026년 소상공인 지원사업 세부 공고", published_year: int = 2026):
    return SourceDocument(
        source_id="SRC-QUALITY",
        canonical_url="https://www.gangnam.go.kr/notice/2026-support/view.do",
        publisher="강남구청",
        source_type=SourceType.OFFICIAL_LOCAL_GOV,
        published_at=datetime(published_year, 2, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
        title=title,
        body_text=body,
        body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        access_status=AccessStatus.OK,
        http_status=200,
        revision_id="REV-QUALITY",
    )


def test_navigation_only_stale_and_usable_detail_are_distinct() -> None:
    navigation = "\n".join(["홈", "로그인", "전체메뉴", "검색", "목록", "이전", "다음"] * 20)
    nav_result = assess_source_quality(
        source(navigation, title="공지사항 목록"), query="소상공인 지원", as_of_date=date(2026, 7, 30)
    )
    assert not nav_result.usable
    assert "NAVIGATION_ONLY" in nav_result.reason_codes

    stale_body = "2022년 소상공인 지원 공고의 신청 조건과 접수 기간을 안내합니다. " * 20
    stale_result = assess_source_quality(
        source(stale_body, published_year=2022), query="소상공인 지원", as_of_date=date(2026, 7, 30)
    )
    assert not stale_result.usable
    assert "STALE_SOURCE" in stale_result.reason_codes

    detail_body = "2026년 강남구 소상공인 대출이자 지원사업의 신청 기간과 대상 요건을 안내합니다. " * 20
    detail_result = assess_source_quality(
        source(detail_body), query="강남구 소상공인 대출이자 지원", as_of_date=date(2026, 7, 30)
    )
    assert detail_result.usable
    assert detail_result.query_term_matches > 0


def test_redirect_limit_and_expired_grounding_url_have_typed_reasons(tmp_path) -> None:
    settings = Settings(snapshot_dir=tmp_path, max_redirects=1)

    def looping(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://www.seoul.go.kr/next"})

    limited = HttpDocumentFetcher(settings, httpx.MockTransport(looping)).fetch(SearchHit(
        url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/start",
        allowed_domains=["seoul.go.kr"],
        rank=1,
    ))
    assert limited.access_status == AccessStatus.REDIRECT_LIMIT
    assert limited.retrieval_reason_code == "REDIRECT_LIMIT"
    assert len(limited.redirect_chain) == 1

    def expired(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410, headers={"content-type": "text/html"})

    missing = HttpDocumentFetcher(settings, httpx.MockTransport(expired)).fetch(SearchHit(
        url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/expired",
        rank=1,
    ))
    assert missing.access_status == AccessStatus.REDIRECT_EXPIRED
    assert missing.retrieval_reason_code == "REDIRECT_EXPIRED"
