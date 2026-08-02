from __future__ import annotations

import hashlib

import pytest

from src.config.settings import Settings
from src.contracts.source_document import SourceDocument
from src.providers.base import (
    DocumentFetcher,
    SearchHit,
    SearchProvider,
    SearchRequest,
    SearchResultBundle,
)
from src.providers.extraction.fake import FakeEventExtractor
from src.orchestration.run_control import RunControlRegistry
from src.research_agents.policy_regulation.agent import PolicyRegulationResearchAgent
from src.research_agents.macro.agent import MacroResearchAgent
from src.storage import AuditRepository, Database, EventRepository, SourceRepository
from tests.research_fixtures import research_request, source_document


class SimulatedClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class AdvancingSearch(SearchProvider):
    def __init__(self, clock: SimulatedClock, seconds_per_call: float = 31.0) -> None:
        self.clock = clock
        self.seconds_per_call = seconds_per_call
        self.calls = 0

    def search(self, request: SearchRequest) -> SearchResultBundle:
        self.calls += 1
        self.clock.advance(self.seconds_per_call)
        hit = SearchHit(
            url=f"https://www.seoul.go.kr/notice/{self.calls}",
            title=f"Official notice {self.calls}",
            rank=1,
            discovery_query=request.query,
        )
        return SearchResultBundle(
            request_id=request.request_id,
            provider="simulated",
            model="simulated-search-v1",
            hits=[hit],
        )


class DocumentFactoryFetcher(DocumentFetcher):
    def __init__(self, *, timeout_first: bool = False) -> None:
        self.timeout_first = timeout_first
        self.calls = 0

    def fetch(self, hit: SearchHit) -> SourceDocument:
        self.calls += 1
        if self.timeout_first and self.calls == 1:
            raise TimeoutError("simulated document timeout")
        suffix = hashlib.sha256(hit.url.encode()).hexdigest()[:12].upper()
        return source_document(
            source_id=f"SRC-{suffix}", revision_id=f"REV-{suffix}"
        ).model_copy(update={"canonical_url": hit.url})


def build_agent(tmp_path, search, fetcher, settings: Settings) -> MacroResearchAgent:
    database = Database(f"sqlite:///{(tmp_path / 'research-timeout.db').as_posix()}")
    database.migrate()
    return MacroResearchAgent(
        search=search,
        fetcher=fetcher,
        extractor=FakeEventExtractor(),
        source_repo=SourceRepository(database),
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
        settings=settings,
    )


def test_combined_research_duration_can_exceed_sixty_seconds(
    tmp_path, monkeypatch
) -> None:
    clock = SimulatedClock()
    monkeypatch.setattr("src.research_agents.base.time.perf_counter", clock.now)
    search = AdvancingSearch(clock)
    agent = build_agent(
        tmp_path,
        search,
        DocumentFactoryFetcher(),
        Settings(research_agent_wall_clock_limit_seconds=0),
    )

    execution = agent.run(research_request("RUN-SIMULATED-GT-60"))

    assert search.calls == 4
    assert clock.value > 60
    assert execution.bundle.diagnostics.discovered_hit_count == 4
    assert execution.bundle.diagnostics.fetched_document_count == 4
    assert execution.bundle.diagnostics.timeout_stage is None
    assert execution.bundle.diagnostics.configured_limits[
        "agent_wall_clock_limit_seconds"
    ] is None


def test_document_timeout_preserves_other_documents_and_diagnostics(tmp_path) -> None:
    search = AdvancingSearch(SimulatedClock(), seconds_per_call=0)
    fetcher = DocumentFactoryFetcher(timeout_first=True)
    agent = build_agent(
        tmp_path,
        search,
        fetcher,
        Settings(research_agent_wall_clock_limit_seconds=0),
    )

    execution = agent.run(research_request("RUN-DOCUMENT-TIMEOUT-PARTIAL"))

    assert execution.bundle.status == "PARTIAL"
    assert execution.bundle.diagnostics.discovered_hit_count == 4
    assert execution.bundle.diagnostics.fetched_document_count == 3
    assert execution.bundle.diagnostics.operation_timeout_counts == {
        "DOCUMENT_FETCH_TIMEOUT": 1
    }
    assert any(
        failure.code == "DOCUMENT_FETCH_TIMEOUT"
        for failure in execution.bundle.access_failures
    )
    assert execution.bundle.diagnostics.partial_output_counts["documents"] == 3


def test_optional_agent_limit_reserves_a_discovered_document(
    tmp_path, monkeypatch
) -> None:
    clock = SimulatedClock()
    monkeypatch.setattr("src.research_agents.base.time.perf_counter", clock.now)
    search = AdvancingSearch(clock, seconds_per_call=9)
    agent = build_agent(
        tmp_path,
        search,
        DocumentFactoryFetcher(),
        Settings(
            research_agent_wall_clock_limit_seconds=10,
            research_min_documents_after_discovery=1,
            gemini_timeout_seconds=1,
            http_timeout_seconds=1,
            openai_timeout_seconds=1,
        ),
    )

    execution = agent.run(research_request("RUN-RESERVED-DOCUMENT"))

    assert search.calls == 1
    assert execution.bundle.diagnostics.discovered_hit_count == 1
    assert execution.bundle.diagnostics.fetched_document_count == 1
    assert execution.bundle.diagnostics.timeout_stage == "SEARCH_DISCOVERY"
    assert execution.bundle.diagnostics.skipped_counts[
        "optional_total_deadline"
    ] == 3


def test_official_policy_seeds_are_fetched_before_search_discovery(tmp_path) -> None:
    trace: list[str] = []

    class TraceSearch(SearchProvider):
        def search(self, request: SearchRequest) -> SearchResultBundle:
            trace.append("search")
            return SearchResultBundle(
                request_id=request.request_id,
                provider="simulated",
                model="simulated-search-v1",
                hits=[],
            )

    class TraceFetcher(DocumentFactoryFetcher):
        def fetch(self, hit: SearchHit) -> SourceDocument:
            trace.append(f"fetch:{hit.url}")
            return super().fetch(hit)

    database = Database(f"sqlite:///{(tmp_path / 'policy-seeds.db').as_posix()}")
    database.migrate()
    agent = PolicyRegulationResearchAgent(
        search=TraceSearch(),
        fetcher=TraceFetcher(),
        extractor=FakeEventExtractor(),
        source_repo=SourceRepository(database),
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
        settings=Settings(
            research_agent_wall_clock_limit_seconds=0,
            research_official_seed_reserve=2,
        ),
    )

    execution = agent.run(research_request("RUN-POLICY-SEED-ORDER"))

    seed_urls = [
        url for url, _title in PolicyRegulationResearchAgent.GANGNAM_POLICY_SEEDS
    ]
    assert trace[:2] == [f"fetch:{url}" for url in seed_urls]
    assert trace[2] == "search"
    assert all(
        outcome["fetched"]
        for outcome in execution.bundle.metadata["seed_outcomes"]
    )
    assert execution.bundle.diagnostics.configured_limits[
        "official_seed_reserve"
    ] == 2


def test_job_deadline_and_user_cancellation_have_distinct_reasons(
    monkeypatch,
) -> None:
    clock = SimulatedClock()
    monkeypatch.setattr("src.orchestration.run_control.time.monotonic", clock.now)
    registry = RunControlRegistry()

    registry.begin("RUN-JOB-CONTROL", timeout_seconds=5)
    assert registry.stop_reason("RUN-JOB-CONTROL") is None
    clock.advance(5)
    assert registry.stop_reason("RUN-JOB-CONTROL") == "ANALYSIS_JOB_TIMEOUT"

    registry.cancel("RUN-JOB-CONTROL")
    assert registry.stop_reason("RUN-JOB-CONTROL") == "USER_CANCELLED"

    registry.finish("RUN-JOB-CONTROL")
    assert registry.stop_reason("RUN-JOB-CONTROL") is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("research_agent_wall_clock_limit_seconds", -1),
        ("gemini_timeout_seconds", 0),
        ("http_timeout_seconds", 0),
        ("openai_timeout_seconds", 0),
        ("analysis_job_timeout_seconds", 0),
        ("research_min_documents_after_discovery", 0),
        ("research_official_seed_reserve", -1),
    ],
)
def test_invalid_timeout_and_reserve_configuration_is_rejected(field, value) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})
