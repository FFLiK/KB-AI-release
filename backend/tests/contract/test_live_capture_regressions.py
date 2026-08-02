import json

import httpx

from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.base import SearchHit, SearchRequest
from src.providers.search.gemini import GeminiSearchProvider
from src.source_snapshot.fetcher import HttpDocumentFetcher
from src.storage.database import Database
from src.storage.repositories import SourceRepository


def test_gemini_grounding_prompt_includes_allowed_final_domains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompt = payload["contents"][0]["parts"][0]["text"]
        assert "final URL" in prompt
        assert "seoul.go.kr" in prompt
        return httpx.Response(
            200,
            json={
                "candidates": [{
                    "groundingMetadata": {
                        "webSearchQueries": ["site:seoul.go.kr official notice"],
                        "groundingChunks": [],
                    }
                }],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    request = SearchRequest(
        query="official notice",
        domain="LOCAL",
        reasoning_level=ReasoningLevel.LOW,
        max_results=1,
        allowed_domains=["seoul.go.kr"],
        request_id="ALLOWED-DOMAIN-REGRESSION",
    )
    settings = Settings(gemini_api_key="configured-test-key")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        GeminiSearchProvider(settings, client).search(request)


def test_distinct_failed_sources_have_distinct_revision_ids(tmp_path) -> None:
    settings = Settings(snapshot_dir=tmp_path / "snapshots")
    fetcher = HttpDocumentFetcher(
        settings,
        httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    first = fetcher.fetch(SearchHit(
        url="https://first.invalid/notice",
        rank=1,
        allowed_domains=["seoul.go.kr"],
    ))
    second = fetcher.fetch(SearchHit(
        url="https://second.invalid/notice",
        rank=2,
        allowed_domains=["seoul.go.kr"],
    ))

    assert first.body_sha256 == second.body_sha256
    assert first.source_id != second.source_id
    assert first.revision_id != second.revision_id

    database = Database(f"sqlite:///{(tmp_path / 'revisions.db').as_posix()}")
    database.migrate()
    repository = SourceRepository(database)
    repository.save(first, "FAILED-SOURCE-REGRESSION")
    repository.save(second, "FAILED-SOURCE-REGRESSION")
