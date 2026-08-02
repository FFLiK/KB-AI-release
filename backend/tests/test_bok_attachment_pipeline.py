from __future__ import annotations

import httpx

from src.config.settings import Settings
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.base import SearchHit
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.macro.agent import MacroResearchAgent
from src.source_snapshot.fetcher import HttpDocumentFetcher
from src.storage import AuditRepository, Database, EventRepository, SourceRepository
from tests.research_fixtures import research_request


def test_macro_agent_extracts_bok_attachment_when_detail_page_is_incomplete(tmp_path) -> None:
    detail_url = "https://www.bok.or.kr/portal/bbs/B0000245/view.do?nttId=1"
    attachment_url = "https://www.bok.or.kr/portal/decision-20260716.txt"
    detail = b"""
        <html><head><title>Decision</title></head><body>
        <nav>Menu Login Related notices</nav>
        <a href='/portal/decision-20260716.txt'>Official decision text</a>
        </body></html>
    """
    attachment = (
        "The Monetary Policy Board decided on July 16, 2026 to raise the Base Rate "
        "from 2.50% to 2.75%, effective immediately."
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == detail_url:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=detail)
        if str(request.url) == attachment_url:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=attachment)
        return httpx.Response(404)

    database = Database(f"sqlite:///{(tmp_path / 'research.db').as_posix()}")
    database.migrate()
    sources = SourceRepository(database)
    extractor = FakeEventExtractor()
    agent = MacroResearchAgent(
        search=FakeSearchProvider(hits=[SearchHit(
            url=detail_url, rank=1, allowed_domains=["bok.or.kr"],
        )]),
        fetcher=HttpDocumentFetcher(
            Settings(snapshot_dir=tmp_path / "snapshots"), httpx.MockTransport(handler)
        ),
        extractor=extractor,
        source_repo=sources,
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
    )

    execution = agent.run(research_request("RUN-5D3147ED-BOK"))

    assert len(extractor.calls) == 1
    extracted_source_id = extractor.calls[0][0]
    extracted = execution.documents[extracted_source_id]
    assert extracted.canonical_url == attachment_url
    assert extracted.parent_source_id is not None
    assert execution.bundle.metadata["usable_document_count"] == 1
    assert execution.bundle.metadata["bok_recovery_diagnostics"] == [{
        "source_id": next(source_id for source_id, source in execution.documents.items() if source.canonical_url == detail_url),
        "reason_codes": ["BOK_ATTACHMENT_DOCUMENT_RECOVERED"],
        "detail_discovered": False,
        "detail_fetched": False,
        "attachment_discovered": True,
        "attachment_fetched": True,
        "text_extracted": True,
        "decision_facts_validated": True,
        "terminal_reason": None,
    }]
from src.source_snapshot.bok import parse_bok_decision
from tests.research_fixtures import source_document


def test_bok_hold_requires_one_current_rate_and_becomes_reference_only(tmp_path) -> None:
    decision_url = "https://www.bok.or.kr/portal/bbs/B0000245/view.do?nttId=hold"
    decision = (
        "<html><head><title>Monetary policy decision</title></head><body>"
        "The Monetary Policy Board decided on July 16, 2026 to maintain the Base Rate "
        "unchanged at 2.50%. This official decision remains effective until the next meeting."
        "</body></html>"
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == decision_url:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=decision)
        return httpx.Response(404)

    database = Database(f"sqlite:///{(tmp_path / 'hold.db').as_posix()}")
    database.migrate()
    extractor = FakeEventExtractor()
    agent = MacroResearchAgent(
        search=FakeSearchProvider(hits=[SearchHit(
            url=decision_url, rank=1, allowed_domains=["bok.or.kr"],
        )]),
        fetcher=HttpDocumentFetcher(
            Settings(snapshot_dir=tmp_path / "hold-snapshots"), httpx.MockTransport(handler)
        ),
        extractor=extractor,
        source_repo=SourceRepository(database),
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
    )

    execution = agent.run(research_request("RUN-BOK-HOLD"))

    assert extractor.calls == []
    assert len(execution.findings) == 1
    assert execution.findings[0].reason_code == "BOK_RATE_HOLD_REFERENCE_ONLY"
    assert execution.findings[0].financial_signal_eligible is False
    assert execution.bundle.document_outcomes[-1].extraction_attempted is False


def test_bok_parser_normalizes_korean_pdf_artifacts_for_hold_and_change() -> None:
    hold = source_document(body=(
        "2026\ub144 7\uc6d4 16\uc77c \ud55c\uad6d\uc740\ud589 \uae08\uc735\ud1b5\ud654\uc704\uc6d0\ud68c\ub294 "
        "\uae30\uc900\uae08\ub9ac\ub97c \uc5f0 2 . 5 0 %\ub85c \ub3d9\uacb0\ud558\uae30\ub85c \uacb0\uc815\ud558\uc600\ub2e4."
    ))
    hold_assessment = parse_bok_decision(hold)
    assert hold_assessment.usable is True
    assert hold_assessment.facts is not None
    assert hold_assessment.facts.decision_type == "HOLD"
    assert hold_assessment.facts.current_rate_percent == "2.50"
    assert hold_assessment.facts.previous_rate_percent is None

    change = source_document(body=(
        "The Monetary Policy Board decided on July 16, 2026 to lower the Base Rate "
        "from 2.75% to 2.50%."
    ))
    change_assessment = parse_bok_decision(change)
    assert change_assessment.usable is True
    assert change_assessment.facts is not None
    assert change_assessment.facts.decision_type == "DECREASE"
    assert change_assessment.facts.previous_rate_percent == "2.75"
    assert change_assessment.facts.new_rate_percent == "2.50"


def test_bok_change_rejection_names_the_missing_rate_facts() -> None:
    incomplete = source_document(body=(
        "The Monetary Policy Board decided on July 16, 2026 to raise the Base Rate to 2.75%."
    ))
    assessment = parse_bok_decision(incomplete)
    assert assessment.usable is False
    assert assessment.reason_codes == ["BOK_RATE_CHANGE_VALUES_INCOMPLETE"]


def test_full_bok_document_anchors_hold_rate_and_ignores_later_forecasts() -> None:
    body = (
        "2026\ub144 2\uc6d4 26\uc77c \ud1b5\ud654\uc815\ucc45\ubc29\ud5a5\n"
        "\u25a1 2026\ub144 2\uc6d4 26\uc77c \uae08\uc735\ud1b5\ud654\uc704\uc6d0\ud68c\ub294 \ub2e4\uc74c \ud1b5\ud654\uc815\ucc45\ubc29\ud5a5 "
        "\uacb0\uc815 \uc2dc\uae4c\uc9c0 \ud55c\uad6d\uc740\ud589 \uae30\uc900\uae08\ub9ac\ub97c \ud604 \uc218\uc900(2.50%)\uc5d0\uc11c \uc720\uc9c0\ud558\uae30\ub85c \ud558\uc600\ub2e4.\n"
        "\u25a1 \uae08\ub144 \uc131\uc7a5\ub960\uc740 2.0%\ub85c \uc804\ub9dd\ub41c\ub2e4. "
        "\uc18c\ube44\uc790\ubb3c\uac00\uc640 \uadfc\uc6d0\ubb3c\uac00 \uc0c1\uc2b9\ub960\uc740 2.2% \ubc0f 2.1%\ub85c \uc804\ub9dd\ub41c\ub2e4.\n"
        "\u25a1 6\uac1c\uc6d4 \ud6c4 \uc870\uac74\ubd80 \uae30\uc900\uae08\ub9ac \uc804\ub9dd \ucc28\ud2b8: 2.75% 2.50% 2.25% 2.00%."
    )
    document = source_document(body=body).model_copy(update={
        "canonical_url": "https://www.bok.or.kr/portal/decision/20260226",
        "title": "Bank of Korea monetary-policy decision",
    })

    assessment = parse_bok_decision(document)

    assert assessment.usable is True
    assert assessment.facts is not None
    assert assessment.facts.current_rate_percent == "2.50"
    assert assessment.facts.rate_selection_method == "DECISION_CLAUSE_ANCHORED"
    assert "2.50%" in assessment.facts.evidence_text
    assert "2.1%" not in assessment.facts.evidence_text
    assert document.body_text[
        assessment.facts.evidence_start_offset:assessment.facts.evidence_end_offset
    ] == assessment.facts.evidence_text


def test_bok_hold_with_multiple_decision_clause_rates_is_ambiguous() -> None:
    document = source_document(body=(
        "The Monetary Policy Board decision on July 16, 2026 was to maintain the Base Rate "
        "at either 2.50% or 2.75%."
    ))

    assessment = parse_bok_decision(document)

    assert assessment.usable is False
    assert assessment.reason_codes == ["BOK_CURRENT_RATE_AMBIGUOUS"]


def test_bok_rate_change_relationship_is_required_and_directional() -> None:
    increase = source_document(body=(
        "The Monetary Policy Board decided on July 16, 2026 to raise the Base Rate "
        "from 2.50% to 2.75%."
    ))
    assessment = parse_bok_decision(increase)

    assert assessment.usable is True
    assert assessment.facts is not None
    assert assessment.facts.decision_type == "INCREASE"
    assert assessment.facts.previous_rate_percent == "2.50"
    assert assessment.facts.new_rate_percent == "2.75"


def test_bok_multiple_change_relationships_are_ambiguous() -> None:
    document = source_document(body=(
        "The Monetary Policy Board decided on July 16, 2026 to lower the Base Rate "
        "from 3.00% to 2.75% or from 2.75% to 2.50%."
    ))

    assessment = parse_bok_decision(document)

    assert assessment.usable is False
    assert assessment.reason_codes == ["BOK_RATE_CHANGE_VALUES_AMBIGUOUS"]


def test_bok_official_ecos_conflict_quarantines_document_value() -> None:
    document = source_document(body=(
        "The Monetary Policy Board decided on July 16, 2026 to maintain the Base Rate "
        "unchanged at 2.50%."
    ))

    assessment = parse_bok_decision(document, official_rate_percent="2.75")

    assert assessment.usable is False
    assert assessment.facts is not None
    assert assessment.reason_codes == ["BOK_RATE_OFFICIAL_DATA_CONFLICT"]


def test_analysis_cross_validation_quarantines_conflicting_bok_reference() -> None:
    from datetime import UTC, date, datetime
    from decimal import Decimal

    from src.contracts.attribution import ResearchFinding
    from src.contracts.official import CanonicalObservation, OfficialDataBundle
    from src.contracts.research import (
        AgentType,
        DocumentResearchOutcome,
        DocumentResearchStatus,
        ResearchBundle,
        ResearchRunStatus,
    )
    from src.orchestration.analysis_orchestrator import (
        _cross_validate_bok_reference_findings,
    )
    from src.orchestration.research_pipeline import ResearchPipelineResult

    document = source_document(body=(
        "The Monetary Policy Board decided on February 26, 2026 to maintain the Base Rate "
        "unchanged at 2.50%."
    )).model_copy(update={
        "canonical_url": "https://www.bok.or.kr/portal/decision/20260226",
    })
    finding = ResearchFinding(
        finding_id="FND-BOK-CONFLICT",
        research_run_id="RUN-BOK-CONFLICT",
        agent_type="MACRO",
        domain="MACRO",
        title="Bank of Korea base-rate decision",
        relevance_summary="Bank of Korea held the base rate at 2.50% on February 26, 2026.",
        source_ids=[document.source_id],
        source_revision_ids=[document.revision_id],
        reason_code="BOK_RATE_HOLD_REFERENCE_ONLY",
    )
    outcome = DocumentResearchOutcome(
        source_id=document.source_id,
        source_revision_id=document.revision_id,
        agent_type=AgentType.MACRO,
        status=DocumentResearchStatus.REFERENCE_FINDINGS_ONLY,
    )
    bundle = ResearchBundle(
        research_run_id="RUN-BOK-CONFLICT",
        agent_type=AgentType.MACRO,
        status=ResearchRunStatus.COMPLETED,
        document_outcomes=[outcome],
    )
    research = ResearchPipelineResult(
        run_id="RUN-BOK-CONFLICT",
        bundles=[bundle],
        documents={document.source_id: document},
        findings=[finding],
    )
    observation = CanonicalObservation(
        observation_id="OBS-BASE-RATE-CONFLICT",
        indicator_id="BASE_RATE",
        value=Decimal("2.75"),
        unit="PERCENT",
        frequency="MONTHLY",
        observed_at=date(2026, 2, 28),
        released_at=datetime(2026, 3, 1, tzinfo=UTC),
        available_at=datetime(2026, 3, 1, tzinfo=UTC),
        source_id="SRC-ECOS",
        source_revision_id="REV-ECOS",
        vintage_id="VINTAGE-ECOS",
    )
    official = OfficialDataBundle(
        snapshot_id="OFFICIAL-BOK-CONFLICT",
        as_of_date=date(2026, 7, 21),
        observations=[observation],
        status="COMPLETED",
    )

    _cross_validate_bok_reference_findings(research, official)

    assert research.findings == []
    assert "BOK_RATE_OFFICIAL_DATA_CONFLICT" in outcome.reason_codes
    assert bundle.metadata["reference_rejection_diagnostics"][0]["official_observation_id"] == observation.observation_id
