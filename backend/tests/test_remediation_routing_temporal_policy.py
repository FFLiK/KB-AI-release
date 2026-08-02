from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.contracts.event_candidate import (
    Domain,
    EventImpact,
    EventType,
    EvidenceRef,
    ExtractedEventCandidate,
    ExtractionMetadata,
    ImpactAxis,
    ImpactDirection,
    LocationRaw,
    TemporalRaw,
)
from src.contracts.policy_candidate import PolicyCandidate, PolicyType, RepaymentTerms
from src.contracts.source_document import AccessStatus, SourceDocument, SourceType
from src.normalization.numeric_unit_normalizer import normalize_numeric_unit
from src.validation.policy_validator import validate_policy_candidate
from src.validation.research_validator import ResearchEventValidator
from tests.research_fixtures import research_request


def _document(body: str, *, published_at: datetime | None = None) -> SourceDocument:
    import hashlib

    source_id = "SRC-REMEDIATION"
    digest = hashlib.sha256(body.encode()).hexdigest()
    return SourceDocument(
        source_id=source_id,
        canonical_url="https://www.gangnam.go.kr/notice/view.do?id=1",
        source_type=SourceType.OFFICIAL_LOCAL_GOV,
        published_at=published_at,
        retrieved_at=datetime.now(UTC),
        title="Official notice",
        body_text=body,
        body_sha256=digest,
        access_status=AccessStatus.OK,
        revision_id="REV-REMEDIATION",
    )


def _candidate(document: SourceDocument, *, event_type: EventType, end_raw: str | None = None) -> ExtractedEventCandidate:
    quote = document.body_text
    evidence = EvidenceRef(
        evidence_id="EVD-REMEDIATION",
        source_id=document.source_id,
        source_revision_id=document.revision_id,
        field_paths=["event_type", "temporal.start_raw", "impacts[0].axis"],
        quote=quote,
        start_offset=0,
        end_offset=len(quote),
    )
    return ExtractedEventCandidate(
        candidate_id="CND-REMEDIATION",
        research_run_id="RUN-REMEDIATION",
        domain=Domain.INDUSTRY,
        event_family="INGREDIENT_SUPPLY",
        event_type=event_type,
        title="Price notice",
        temporal=TemporalRaw(start_raw="2024-06-01", end_raw=end_raw),
        location=LocationRaw(area_raw="Seoul"),
        affected_industries_raw=["FNB"],
        impacts=[EventImpact(
            axis=ImpactAxis.INGREDIENT_COST,
            direction=ImpactDirection.INCREASE,
            mechanism="WHOLESALE_PRICE_CHANGE",
            evidence_ids=[evidence.evidence_id],
        )],
        evidence=[evidence],
        extraction_metadata=ExtractionMetadata(model="test", prompt_version="test"),
    )


def test_historical_price_article_is_reference_only_not_forecast_event() -> None:
    document = _document(
        "2024-06-01 wholesale coffee price increase report.",
        published_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    outcome = ResearchEventValidator().validate(
        _candidate(document, event_type=EventType.WHOLESALE_PRICE_INCREASE),
        {document.source_id: document},
        research_request("RUN-REMEDIATION"),
    )

    assert outcome.status == "REFERENCE_ONLY"
    assert outcome.failure_codes == ["HISTORICAL_CONTEXT_ONLY"]


def test_missing_end_requires_explicit_ongoing_evidence() -> None:
    document = _document("2026-08-01 construction notice.")
    candidate = _candidate(document, event_type=EventType.INPUT_SUPPLY_DISRUPTION)
    candidate = candidate.model_copy(update={
        "domain": Domain.MACRO,
        "event_family": "INPUT_MARKET",
        "impacts": [EventImpact(
            axis=ImpactAxis.INGREDIENT_COST,
            direction=ImpactDirection.INCREASE,
            mechanism="SUPPLY_DISRUPTION",
            evidence_ids=[candidate.evidence[0].evidence_id],
        )],
    })
    outcome = ResearchEventValidator().validate(
        candidate, {document.source_id: document}, research_request("RUN-ONGOING"),
    )

    assert outcome.status == "REFERENCE_ONLY"
    assert "MISSING_ONGOING_EVIDENCE" in outcome.failure_codes


def test_policy_semantics_compare_currency_and_years_after_normalization() -> None:
    body = "Limit 3억원. Repayment period 4년."
    document = _document(body)
    evidence = EvidenceRef(
        evidence_id="EVD-POLICY", source_id=document.source_id, source_revision_id=document.revision_id,
        field_paths=["limit_krw", "repayment_terms.maturity_months"], quote=body,
        start_offset=0, end_offset=len(body),
    )
    policy = PolicyCandidate(
        policy_candidate_id="POL-REMEDIATION", research_run_id="RUN-REMEDIATION",
        policy_type=PolicyType.LOAN_SUPPORT, name="Working capital", provider_raw="Gangnam",
        limit_krw=Decimal("300000000"), repayment_terms=RepaymentTerms(maturity_months=48),
        source_ids=[document.source_id], evidence=[evidence],
    )

    validated = validate_policy_candidate(policy, {document.source_id: document}, date(2026, 7, 30))
    assert validated.validation_status == "VALIDATED"
    assert any(note.endswith("300000000 KRW") for note in validated.validation_notes)
    assert normalize_numeric_unit("1년").normalized_unit == "YEARS"