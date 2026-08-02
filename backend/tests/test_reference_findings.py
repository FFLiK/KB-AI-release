import pytest
from pydantic import ValidationError

from pathlib import Path

from src.contracts.event_candidate import EvidenceRef
from src.contracts.research import DocumentResearchStatus
from src.providers.base import ExtractionResult, SearchHit
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.macro.agent import MacroResearchAgent
from src.storage import AuditRepository, Database, EventRepository, SourceRepository
from tests.research_fixtures import StaticFetcher, research_request, source_document

from src.contracts.attribution import ResearchFinding


def test_reference_finding_is_display_only_by_construction() -> None:
    finding = ResearchFinding(
        finding_id="FND-1",
        research_run_id="RUN-1",
        agent_type="INDUSTRY",
        domain="INDUSTRY",
        title="원재료 관련 참고 자료",
        relevance_summary="관련성은 있으나 적용 기간과 재무 영향 근거가 부족합니다.",
        source_ids=["SRC-1"],
        source_revision_ids=["REV-1"],
        missing_requirements=["TEMPORAL_EVIDENCE", "IMPACT_EVIDENCE"],
        reason_code="INSUFFICIENT_TEMPORAL_EVIDENCE",
    )
    assert finding.financial_signal_eligible is False
    assert finding.model_dump()["financial_signal_eligible"] is False

    with pytest.raises(ValidationError):
        ResearchFinding.model_validate({
            **finding.model_dump(),
            "financial_signal_eligible": True,
        })


def test_temporal_gap_blocks_time_sensitive_reference(tmp_path: Path) -> None:
    body = (
        "Official construction notice confirms the pedestrian route near Gangnam Road will be "
        "partially closed while safety work proceeds, but it does not state an effective date."
    )
    document = source_document(body=body).model_copy(update={
        "source_trust_level": "OFFICIAL_TRUSTED",
    })
    evidence = EvidenceRef(
        evidence_id="EVD-REF", source_id=document.source_id,
        source_revision_id=document.revision_id, field_paths=["reference_summary"],
        quote=body, start_offset=0, end_offset=len(body),
    )
    extraction = ExtractionResult(
        request_id="REF-1", provider="fake", model="fake", document_status="INSUFFICIENT_TEMPORAL_EVIDENCE",
        reference_summary="Official construction notice confirms a partial pedestrian route closure near Gangnam Road.",
        reference_evidence=[evidence],
    )
    database = Database(f"sqlite:///{(tmp_path / 'reference.db').as_posix()}")
    database.migrate()
    agent = MacroResearchAgent(
        search=FakeSearchProvider(hits=[SearchHit(url=document.canonical_url, rank=1)]),
        fetcher=StaticFetcher(document), extractor=FakeEventExtractor(results_by_source={document.source_id: extraction}),
        source_repo=SourceRepository(database), event_repo=EventRepository(database), audit_repo=AuditRepository(database),
    )

    execution = agent.run(research_request("RUN-REFERENCE-FALLBACK"))

    assert execution.candidates == []
    assert execution.findings == []
    assert execution.bundle.document_outcomes[-1].status == DocumentResearchStatus.INSUFFICIENT_TEMPORAL_EVIDENCE
    assert "REFERENCE_NO_ONGOING_RELEVANCE" in execution.bundle.document_outcomes[-1].reason_codes


def test_navigation_shell_cannot_be_promoted_to_reference(tmp_path: Path) -> None:
    body = "Menu Login Search Sitemap Contact Copyright Menu Login Search Sitemap Contact Copyright"
    document = source_document(body=body).model_copy(update={"source_trust_level": "OFFICIAL_TRUSTED"})
    evidence = EvidenceRef(evidence_id="EVD-NAV", source_id=document.source_id, source_revision_id=document.revision_id,
                           field_paths=["reference_summary"], quote=body, start_offset=0, end_offset=len(body))
    extraction = ExtractionResult(request_id="REF-NAV", provider="fake", model="fake", document_status="REFERENCE_FINDINGS_ONLY",
                                  reference_summary="Official notice reports a menu and contact listing.", reference_evidence=[evidence])
    database = Database(f"sqlite:///{(tmp_path / 'navigation.db').as_posix()}")
    database.migrate()
    agent = MacroResearchAgent(search=FakeSearchProvider(hits=[SearchHit(url=document.canonical_url, rank=1)]),
        fetcher=StaticFetcher(document), extractor=FakeEventExtractor(results_by_source={document.source_id: extraction}),
        source_repo=SourceRepository(database), event_repo=EventRepository(database), audit_repo=AuditRepository(database))

    assert agent.run(research_request("RUN-NAVIGATION-REFERENCE")).findings == []

def test_irrelevant_regional_statistics_cannot_be_promoted_to_reference() -> None:
    body = (
        "Regional statistics report household counts, library visits, and public park usage for the district "
        "during 2026. The report does not address storefront conditions."
    )
    document = source_document(body=body).model_copy(update={"source_trust_level": "OFFICIAL_TRUSTED", "title": "Regional statistics"})
    evidence = EvidenceRef(evidence_id="EVD-STATS", source_id=document.source_id, source_revision_id=document.revision_id,
                           field_paths=["reference_summary"], quote=body, start_offset=0, end_offset=len(body))
    agent = MacroResearchAgent(search=None, fetcher=None, extractor=None, source_repo=None, event_repo=None, audit_repo=None)

    finding, diagnostic = agent._reference_finding_with_diagnostic(
        research_request("RUN-REGIONAL-STATS"), document, "REFERENCE_FINDINGS_ONLY",
        "Regional statistics report household counts and park usage for the district.", [evidence],
        query="construction closure business access",
    )
    assert finding is None
    assert diagnostic == "REFERENCE_QUERY_IRRELEVANT"

def test_stale_proposal_retains_all_temporal_rejection_diagnostics() -> None:
    body = (
        "Official public comment proposal published 2024-09-01 covered proposed "
        "2025 quota-tariff items. Comments closed on 2024-10-01, and this notice "
        "does not confirm adoption or implementation."
    )
    document = source_document(body=body).model_copy(update={
        "source_trust_level": "OFFICIAL_TRUSTED",
        "title": "Expired quota-tariff public comment proposal",
    })
    evidence = EvidenceRef(
        evidence_id="EVD-STALE-PROPOSAL",
        source_id=document.source_id,
        source_revision_id=document.revision_id,
        field_paths=["reference_summary"],
        quote=body,
        start_offset=0,
        end_offset=len(body),
    )
    agent = MacroResearchAgent(
        search=None, fetcher=None, extractor=None,
        source_repo=None, event_repo=None, audit_repo=None,
    )

    finding, diagnostics = agent._reference_finding_with_diagnostic(
        research_request("RUN-STALE-PROPOSAL"),
        document,
        "REFERENCE_FINDINGS_ONLY",
        "Official public comment proposal covered proposed 2025 quota-tariff items.",
        [evidence],
    )

    assert finding is None
    assert diagnostics == [
        "REFERENCE_STALE_PROPOSAL",
        "REFERENCE_IMPLEMENTATION_UNCONFIRMED",
    ]
