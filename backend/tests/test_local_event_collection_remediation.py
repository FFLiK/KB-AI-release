from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from src.config.settings import Settings
from src.contracts.research import AgentType
from src.forecasting.official_event_bridge import apply_official_event_bridge
from src.normalization.date_normalizer import normalize_date
from src.normalization.region_normalizer import canonical_region_id, regions_match
from src.providers.base import SearchHit
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.local_event.agent import LocalEventResearchAgent
from src.source_snapshot.fetcher import HttpDocumentFetcher
from src.storage import AuditRepository, Database, EventRepository, SourceRepository
from tests.research_fixtures import research_request
from tests.test_run_d0dcee2c_94a_remediation import observation, official_bundle, rate_event


def test_local_structured_list_traverses_canonical_details_once(tmp_path: Path) -> None:
    list_url = "https://www.seoul.go.kr/events/list"
    first_url = "https://www.seoul.go.kr/events/view.do?id=1"
    second_url = "https://www.seoul.go.kr/events/view.do?id=2"
    listing = b"""
        <html><head><title>Official event list</title></head><body><main>
        <h1>Upcoming events</h1>
        <ul>
          <li>2026-08-10 Gangnam-gu COEX <a href='/events/view.do?id=1'>Festival details</a></li>
          <li>2026-08-17 Gangnam-gu Station <a href='/events/view.do?id=2'>Construction details</a></li>
        </ul></main></body></html>
    """
    details = {
        first_url: b"<html><body><main>2026-08-10 Gangnam-gu COEX official festival event.</main></body></html>",
        second_url: b"<html><body><main>2026-08-17 Gangnam-gu Station official construction notice.</main></body></html>",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == list_url:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=listing)
        if url in details:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=details[url])
        return httpx.Response(404)

    database = Database(f"sqlite:///{(tmp_path / 'local.db').as_posix()}")
    database.migrate()
    extractor = FakeEventExtractor()
    agent = LocalEventResearchAgent(
        search=FakeSearchProvider(hits=[SearchHit(url=list_url, rank=1)]),
        fetcher=HttpDocumentFetcher(Settings(snapshot_dir=tmp_path / "snapshots"), httpx.MockTransport(handler)),
        extractor=extractor,
        source_repo=SourceRepository(database),
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
    )

    execution = agent.run(research_request("RUN-LOCAL-TRAVERSAL"))

    assert len(extractor.calls) == 2  # list rows route only; only relevant details are extracted
    assert all(document.parent_source_id for document in execution.documents.values() if document.canonical_url in details)
    assert execution.bundle.metadata["local_collection"] == {
        "structured_listings": 1,
        "detail_links_discovered": 2,
        "detail_pages_fetched": 2,
        "attachments_fetched": 0,
        "list_row_candidates": 2,
        "excluded_irrelevant_rows": 0,
        "unique_detail_targets": 2,
        "skipped_detail_duplicates": 0,
        "extracted_detail_pages": 2,
        "detail_targets_scheduled": 2,
        "detail_targets_skipped": 0,
        "detail_targets_failed": 0,
        "detail_target_outcomes": [
            {"url": first_url, "outcome": "DETAIL_FETCHED"},
            {"url": second_url, "outcome": "DETAIL_FETCHED"},
        ],
    }
    assert any(item.status == "STRUCTURED_LIST_TRAVERSED" for item in execution.bundle.document_outcomes)


def test_region_date_and_foreign_rate_guards_are_deterministic() -> None:
    assert canonical_region_id("11680") == canonical_region_id("KR-11680") == "KR-11680"
    assert regions_match("11680", ["\uc11c\uc6b8 \uac15\ub0a8\uad6c"]) is True
    parsed, rule = normalize_date("'26.7.30.(\ubaa9) 08:00", date(2026, 7, 1))
    assert parsed == date(2026, 7, 30)
    assert rule == "KO_DATE_TWO_DIGIT_YEAR_V1"

    event = rate_event().model_copy(deep=True)
    event.actor_org_raw = "Federal Reserve FOMC"
    event.attributes["official_indicator_id"] = "\uae30\uc900\uae08\ub9ac"
    bundle = official_bundle(observation(date(2026, 6, 30), "2.50", "OBS-JUN"))
    _, decisions = apply_official_event_bridge(bundle, [event])
    assert decisions[0].status == "INELIGIBLE"
    assert decisions[0].reason_code == "ACTOR_NOT_AUTHORIZED_FOR_BASE_RATE"
