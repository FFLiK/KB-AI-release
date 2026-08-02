import json

import httpx

from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.base import SearchRequest
from src.providers.search.gemini import GeminiSearchProvider


def test_gemini_prompt_explicitly_requires_google_search() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompt = payload["contents"][0]["parts"][0]["text"]
        assert "Use Google Search for this request" in prompt
        assert payload["tools"] == [{"google_search": {}}]
        return httpx.Response(
            200,
            json={
                "candidates": [{
                    "groundingMetadata": {
                        "webSearchQueries": ["official source"],
                        "groundingChunks": [],
                    }
                }],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    request = SearchRequest(
        query="official announcement",
        domain="POLICY",
        reasoning_level=ReasoningLevel.LOW,
        max_results=1,
        allowed_domains=["gov.kr"],
        request_id="GROUNDING-REQUEST-REGRESSION",
    )
    settings = Settings(gemini_api_key="configured-test-key")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = GeminiSearchProvider(settings, client).search(request)

    assert result.raw_metadata["grounding_present"] is True
    assert result.raw_metadata["search_query_count"] == 1
