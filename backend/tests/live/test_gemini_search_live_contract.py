import pytest

from src.config.credential_validation import get_credential
from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.base import SearchProviderError, SearchRequest
from src.providers.search.gemini import GeminiSearchProvider


pytestmark = pytest.mark.live

CASES = (
    ("MACRO", "2026년 한국은행 기준금리 공식 발표", ["bok.or.kr"]),
    ("INDUSTRY", "2026년 커피 생두 수급 공식 발표", ["mafra.go.kr", "at.or.kr"]),
    ("LOCAL", "2026년 서울 강남구 도로 공사 공식 공고", ["seoul.go.kr"]),
    ("POLICY", "2026년 음식점 규제 공식 공고", ["mfds.go.kr", "gov.kr"]),
)


@pytest.mark.parametrize(("domain", "query", "allowed_domains"), CASES)
def test_gemini_live_grounded_discovery_contract(domain, query, allowed_domains) -> None:
    if not get_credential("GEMINI_API_KEY"):
        pytest.skip("Gemini credential is not configured")
    settings = Settings()
    provider = GeminiSearchProvider(settings)
    result = None
    for attempt in range(settings.max_search_retries + 1):
        try:
            result = provider.search(SearchRequest(
                query=query,
                domain=domain,
                reasoning_level=ReasoningLevel.LOW,
                max_results=3,
                allowed_domains=allowed_domains,
                request_id=f"LIVE-GEMINI-{domain}-{attempt + 1}",
            ))
        except SearchProviderError as exc:
            if exc.code != "TIMEOUT" or attempt == settings.max_search_retries:
                raise
            continue
        if result.raw_metadata["grounding_present"]:
            break
    assert result is not None

    assert result.latency_ms <= 90_000
    assert result.input_tokens > 0 and result.output_tokens >= 0
    assert result.raw_metadata["grounding_present"] is True
    assert result.raw_metadata["search_query_count"] > 0
    assert len(result.hits) <= 3
    assert result.hits or result.raw_metadata["result_status"] == "NO_GROUNDED_URLS"
    assert all(hit.allowed_domains == allowed_domains for hit in result.hits)
