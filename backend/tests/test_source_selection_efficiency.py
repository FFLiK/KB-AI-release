from __future__ import annotations

from src.providers.base import DocumentFetcher, SearchHit
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.macro.agent import MacroResearchAgent
from src.storage import AuditRepository, Database, EventRepository, SourceRepository
from tests.research_fixtures import research_request, source_document


class CountingFetcher(DocumentFetcher):
    def __init__(self) -> None:
        self.calls = 0
        self.document = source_document()

    def fetch(self, _hit: SearchHit):
        self.calls += 1
        return self.document


def test_canonical_duplicate_urls_are_removed_before_fetching(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'selection.db').as_posix()}")
    database.migrate()
    fetcher = CountingFetcher()
    agent = MacroResearchAgent(
        search=FakeSearchProvider(hits=[
            SearchHit(url="https://www.seoul.go.kr/notice?a=1&utm_source=first", rank=1),
            SearchHit(url="HTTPS://www.seoul.go.kr/notice?utm_medium=second&a=1#fragment", rank=2),
        ]),
        fetcher=fetcher,
        extractor=FakeEventExtractor(),
        source_repo=SourceRepository(database),
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
    )

    execution = agent.run(research_request("RUN-SOURCE-SELECTION"))

    assert fetcher.calls == 1
    assert execution.bundle.metadata["discovery_hit_count"] == 1
    assert execution.bundle.metadata["deduplicated_document_count"] == 0
