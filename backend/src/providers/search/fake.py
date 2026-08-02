from __future__ import annotations

from src.providers.base import SearchHit, SearchProvider, SearchRequest, SearchResultBundle


class FakeSearchProvider(SearchProvider):
    def __init__(self, hits: list[SearchHit] | None = None, by_domain: dict[str, list[SearchHit]] | None = None):
        self.hits = hits or []
        self.by_domain = by_domain or {}
        self.calls: list[SearchRequest] = []

    def search(self, request: SearchRequest) -> SearchResultBundle:
        self.calls.append(request)
        hits = self.by_domain.get(request.domain, self.hits)[:request.max_results]
        return SearchResultBundle(request_id=request.request_id, provider="fake", model="fake-search-v1", hits=hits,
                                  input_tokens=len(request.query), output_tokens=len(hits), latency_ms=0)
