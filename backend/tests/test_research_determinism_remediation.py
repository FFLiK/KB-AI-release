from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from src.contracts.research import AgentType
from src.contracts.source_document import SourceDocument
from src.providers.base import (
    DocumentFetcher, SearchHit, SearchProvider, SearchProviderError, SearchRequest,
)
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.industry.agent import IndustryResearchAgent
from src.research_agents.policy_regulation.agent import PolicyRegulationResearchAgent
from src.source_snapshot.quality_gate import SourceDisposition, assess_source_quality
from src.source_snapshot.source_policy import (
    classify_source, classify_source_role, classify_source_trust,
    source_authority_registry,
)
from src.storage import AuditRepository, Database, EventRepository, SourceRepository
from src.validation.research_validator import ResearchEventValidator
from tests.research_fixtures import candidate, research_request, source_document


def _revision(document: SourceDocument, **updates) -> SourceDocument:
    payload = document.model_dump(mode="json")
    payload.update(updates)
    payload["snapshot_fingerprint"] = None
    revised = SourceDocument.model_validate(payload)
    material = f"{revised.source_id}|{revised.snapshot_fingerprint}".encode()
    return revised.model_copy(update={
        "revision_id": "REV-" + hashlib.sha256(material).hexdigest()[:20].upper()
    })


def test_metadata_only_source_change_creates_a_new_revision(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'revisions.db').as_posix()}")
    database.migrate()
    repository = SourceRepository(database)
    first = _revision(source_document(), detail_urls=[])
    second = _revision(first, detail_urls=["https://www.seoul.go.kr/detail/1"])

    stored_first, created_first = repository.save(first, "RUN-FIRST")
    stored_second, created_second = repository.save(second, "RUN-SECOND")

    assert created_first is True
    assert created_second is True
    assert stored_first.body_sha256 == stored_second.body_sha256
    assert stored_first.snapshot_fingerprint != stored_second.snapshot_fingerprint
    assert repository.list_revisions(first.source_id) == [
        first.revision_id, second.revision_id,
    ]


def test_fresh_and_populated_databases_return_same_snapshot(tmp_path: Path) -> None:
    initial = _revision(source_document(), detail_urls=[])
    current = _revision(
        initial,
        detail_urls=["https://www.seoul.go.kr/detail/1"],
        final_url_resolved=True,
        classification_reasons=["DETAIL_LINK_DISCOVERED"],
    )
    returned = []
    for name, populate in (("fresh.db", False), ("warm.db", True)):
        database = Database(f"sqlite:///{(tmp_path / name).as_posix()}")
        database.migrate()
        repository = SourceRepository(database)
        if populate:
            repository.save(initial, "RUN-HISTORY")
        returned.append(repository.save(current, "RUN-CURRENT")[0])

    assert returned[0].model_dump(mode="json") == returned[1].model_dump(mode="json")


def test_substantive_policy_page_can_extract_and_traverse() -> None:
    document = _revision(
        source_document(body=(
            "Gangnam District officially provides small-business loan interest support. "
            "Applications are accepted from 2026-07-01 through 2026-12-31, subject to "
            "documented eligibility and available budget."
        )),
        detail_urls=["https://www.gangnam.go.kr/notice/official-application"],
        source_trust_level="OFFICIAL_TRUSTED",
    )
    quality = assess_source_quality(
        document,
        query="Gangnam small business loan interest support",
        as_of_date=date(2026, 8, 2),
        agent_type=AgentType.POLICY_REGULATION,
    )

    assert quality.substantive_content is True
    assert quality.has_detail_links is True
    assert quality.disposition == SourceDisposition.EXTRACT_AND_TRAVERSE
    assert quality.usable is True



class MappingFetcher(DocumentFetcher):
    def __init__(self, documents: list[SourceDocument]):
        self.documents = {document.canonical_url: document for document in documents}

    def fetch(self, hit: SearchHit) -> SourceDocument:
        return self.documents[hit.url]


def test_same_body_different_snapshots_are_both_evaluated(tmp_path: Path) -> None:
    body = (
        "Official food-service market report documents a material supply-cost change "
        "with effective dates and evidence relevant to restaurant operators."
    )
    first = _revision(
        source_document(body=body, source_id="SRC-SNAPSHOT-A"),
        canonical_url="https://kostat.go.kr/report/a",
    )
    second = _revision(
        source_document(body=body, source_id="SRC-SNAPSHOT-B"),
        canonical_url="https://kostat.go.kr/report/b",
        detail_urls=["https://kostat.go.kr/report/b/detail"],
    )
    database = Database(f"sqlite:///{(tmp_path / 'snapshot-routing.db').as_posix()}")
    database.migrate()
    extractor = FakeEventExtractor()
    agent = IndustryResearchAgent(
        search=FakeSearchProvider(hits=[
            SearchHit(url=first.canonical_url, rank=1),
            SearchHit(url=second.canonical_url, rank=2),
        ]),
        fetcher=MappingFetcher([first, second]),
        extractor=extractor,
        source_repo=SourceRepository(database),
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
    )

    execution = agent.run(research_request("RUN-SNAPSHOT-ROUTING"))

    assert first.body_sha256 == second.body_sha256
    assert first.snapshot_fingerprint != second.snapshot_fingerprint
    assert {call[0] for call in extractor.calls} == {first.source_id, second.source_id}
    assert not any(
        "DUPLICATE_SOURCE_SNAPSHOT" in outcome.reason_codes
        for outcome in execution.bundle.document_outcomes
    )
class FailingSearch(SearchProvider):
    def search(self, request: SearchRequest):
        raise SearchProviderError("PROVIDER_FAILURE", http_status=503)


class SeedFetcher(DocumentFetcher):
    def __init__(self):
        self.urls: list[str] = []

    def fetch(self, hit: SearchHit) -> SourceDocument:
        self.urls.append(hit.url)
        body = (
            "Gangnam District provides documented small-business policy support. "
            "Official eligibility, application dates, and budget status require validation."
        )
        base = source_document(body=body).model_copy(update={
            "source_id": "SRC-" + hashlib.sha256(hit.url.encode()).hexdigest()[:20].upper(),
            "canonical_url": hit.url,
            "source_trust_level": "OFFICIAL_TRUSTED",
            "source_type": "OFFICIAL_LOCAL_GOV",
        })
        return _revision(base)


def test_policy_seeds_run_when_search_provider_fails(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'policy.db').as_posix()}")
    database.migrate()
    fetcher = SeedFetcher()
    agent = PolicyRegulationResearchAgent(
        search=FailingSearch(),
        fetcher=fetcher,
        extractor=FakeEventExtractor(),
        source_repo=SourceRepository(database),
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
    )
    execution = agent.run(research_request("RUN-SEEDS-PROVIDER-FAILURE"))

    assert set(fetcher.urls) == {
        url for url, _ in PolicyRegulationResearchAgent.GANGNAM_POLICY_SEEDS
    }
    assert execution.bundle.metadata["seeded_source_count"] == 2
    assert all(item["fetched"] for item in execution.bundle.metadata["seed_outcomes"])
    assert execution.bundle.provider_failures[0].error_code == "PROVIDER_FAILURE"
    assert execution.bundle.search_queries
    assert all(
        item.status == "FAILED"
        and item.failure_code == "PROVIDER_FAILURE"
        and item.retry_count == 1
        for item in execution.bundle.search_queries
    )
    with database.engine.connect() as connection:
        statuses = connection.exec_driver_sql("SELECT status FROM search_queries").scalars().all()
    assert statuses == ["FAILED"] * len(execution.bundle.search_queries)



def test_unresolved_multi_venue_event_cannot_use_arbitrary_coordinates() -> None:
    document = source_document()
    item = candidate(document).model_copy(update={
        "attributes": {
            "closure_scope": "PARTIAL",
            "venues": ["Gangnam Station", "COEX"],
        },
    })

    outcome = ResearchEventValidator().validate(
        item, {document.source_id: document}, research_request()
    )

    assert outcome.event is None
    assert "LOCATION_AMBIGUOUS" in outcome.failure_codes
    assert outcome.validation_metadata["multi_venue_detected"] is True
def test_visitgangnam_authority_is_registry_backed() -> None:
    version, registry = source_authority_registry()
    assert version == "source_authorities.v1"
    assert registry["visitgangnam.net"]["governing_authority"] == "gangnam.go.kr"
    assert str(classify_source("https://visitgangnam.net/event")) == "SourceType.OFFICIAL_LOCAL_GOV"
    assert str(classify_source_trust("https://visitgangnam.net/event")) == "SourceTrustLevel.OFFICIAL_TRUSTED"
    assert str(classify_source_role("https://visitgangnam.net/event")) == "SourceRole.LOCAL_GOVERNMENT"


def test_recorded_run_fixtures_have_stable_hashes() -> None:
    fixture_dir = Path(__file__).parent / "fixtures" / "replay"
    for run_id in (
        "RUN-69F73FE6-5D3", "RUN-15233429-398", "RUN-8DB58EBC-9C0",
        "RUN-160D600E-34E",
        "RUN-932273DA-BE3",
    ):
        payload = json.loads(
            (fixture_dir / f"{run_id}.research.v1.json").read_text(encoding="utf-8")
        )
        expected = payload.pop("fixture_sha256")
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        assert hashlib.sha256(canonical).hexdigest() == expected
        assert payload["request"]["run_id"] == run_id
        if run_id == "RUN-932273DA-BE3":
            assert len(payload["queries"]) == 22
            assert len(payload["ordered_discovery_results"]) == 125
            assert payload["source_revisions"] == []
        else:
            assert payload["source_revisions"]


from src.orchestration.analysis_orchestrator import _run_provenance


def test_dirty_worktree_provenance_is_explicit_and_secret_free(monkeypatch) -> None:
    outputs = {
        ("rev-parse", "HEAD"): "abc123\n",
        ("status", "--porcelain=v1", "--untracked-files=all"): " M src/example.py\n",
        ("diff", "--binary", "HEAD", "--"): "diff --git a/x b/x\n",
        ("ls-files", "--others", "--exclude-standard"): "",
    }
    monkeypatch.setattr(
        "src.orchestration.analysis_orchestrator._git_output",
        lambda *arguments: outputs.get(arguments, ""),
    )

    provenance = _run_provenance({"provider": "fake", "timeout_seconds": 30})

    assert provenance["git_commit"] == "abc123"
    assert provenance["git_dirty"] is True
    assert len(provenance["working_tree_diff_hash"]) == 64
    assert len(provenance["untracked_file_manifest_hash"]) == 64
    assert len(provenance["configuration_fingerprint"]) == 64
    assert "secret" not in str(provenance).casefold()
