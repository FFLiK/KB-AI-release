import httpx

from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.base import SearchRequest
from src.providers.search.gemini import GeminiSearchProvider


def test_gemini_uses_grounded_search_specific_timeout(monkeypatch) -> None:
    captured = {}

    class Client:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def post(self, *args, **kwargs):
            del args, kwargs
            return httpx.Response(
                200,
                json={
                    "candidates": [{
                        "groundingMetadata": {
                            "webSearchQueries": ["official source"],
                            "groundingChunks": [],
                        }
                    }]
                },
            )

        def close(self):
            return None

    monkeypatch.setattr("src.providers.search.gemini.httpx.Client", Client)
    settings = Settings(
        gemini_api_key="configured-test-key",
        gemini_timeout_seconds=37,
        http_timeout_seconds=1,
    )
    request = SearchRequest(
        query="official source",
        domain="MACRO",
        reasoning_level=ReasoningLevel.LOW,
        max_results=1,
        allowed_domains=["bok.or.kr"],
        request_id="GEMINI-TIMEOUT-REGRESSION",
    )

    GeminiSearchProvider(settings).search(request)

    assert captured["timeout"] == 37
