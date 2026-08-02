import json
from pathlib import Path

import httpx
import pytest

from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.base import SearchProviderError, SearchRequest
from src.providers.search.gemini import GeminiSearchProvider


FIXTURE = Path("tests/fixtures/providers/gemini/grounded_search_response.json")


def request() -> SearchRequest:
    return SearchRequest(
        query="한국은행 기준금리 공식 발표",
        domain="MACRO",
        reasoning_level=ReasoningLevel.LOW,
        max_results=2,
        allowed_domains=["bok.or.kr", "moef.go.kr"],
        request_id="SEARCH-CONTRACT-1",
    )


def test_grounded_search_replay_preserves_discovery_metadata_without_key_in_url() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        assert "key=" not in str(http_request.url)
        assert http_request.headers["x-goog-api-key"] == "configured-test-key"
        payload = json.loads(http_request.content)
        assert payload["tools"] == [{"google_search": {}}]
        assert "temperature" not in payload.get("generationConfig", {})
        return httpx.Response(200, json=json.loads(FIXTURE.read_text(encoding="utf-8")))

    settings = Settings(gemini_api_key="configured-test-key", gemini_model="gemini-3.6-flash")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GeminiSearchProvider(settings, client).search(request())

    assert result.provider == "gemini" and len(result.hits) == 2
    assert all(hit.allowed_domains == ["bok.or.kr", "moef.go.kr"] for hit in result.hits)
    assert result.input_tokens == 42 and result.output_tokens == 18 and result.cached_tokens == 3
    assert result.raw_metadata["grounding_present"] is True
    assert result.raw_metadata["search_query_count"] == 1
    assert result.raw_metadata["grounding_support_count"] == 1
    assert "search_entry_point" not in result.raw_metadata


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "AUTHENTICATION_FAILED"), (403, "AUTHENTICATION_FAILED"), (429, "RATE_LIMITED"), (500, "HTTP_500")],
)
def test_gemini_http_failures_are_explicit(status, expected) -> None:
    settings = Settings(gemini_api_key="configured-test-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"error": {"code": status}}))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(SearchProviderError) as caught:
            GeminiSearchProvider(settings, client).search(request())
    assert caught.value.code == expected and caught.value.http_status == status


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, content=b"not-json"), "MALFORMED_RESPONSE"),
        (httpx.Response(200, json={"candidates": []}), "EMPTY_RESPONSE"),
        (httpx.Response(200, json={"candidates": [{"groundingMetadata": {"groundingChunks": {}}}]}), "MALFORMED_GROUNDING"),
    ],
)
def test_gemini_payload_failures_are_explicit(response, expected) -> None:
    settings = Settings(gemini_api_key="configured-test-key")
    with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(SearchProviderError) as caught:
            GeminiSearchProvider(settings, client).search(request())
    assert caught.value.code == expected


def test_gemini_timeout_is_explicit() -> None:
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    settings = Settings(gemini_api_key="configured-test-key")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SearchProviderError) as caught:
            GeminiSearchProvider(settings, client).search(request())
    assert caught.value.code == "TIMEOUT"
