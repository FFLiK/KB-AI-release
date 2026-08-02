from src.validation.reference_temporal import evaluate_reference_freshness
from tests.research_fixtures import research_request, source_document


def _decision(body: str, summary: str | None = None):
    request = research_request("RUN-REFERENCE-FRESHNESS")
    document = source_document(body=body).model_copy(update={
        "title": summary or body,
    })
    return evaluate_reference_freshness(
        request,
        document,
        reference_summary=summary or body,
        evidence_text=body,
    )


def test_expired_proposal_without_adoption_is_blocked() -> None:
    decision = _decision(
        "Public comment proposal published 2024-09-01 for proposed 2025 quota-tariff items. "
        "Comments closed on 2024-10-01; this notice does not confirm adoption."
    )

    assert decision.promotable is False
    assert decision.status == "STALE_PROPOSAL"
    assert decision.reason_codes == [
        "REFERENCE_STALE_PROPOSAL",
        "REFERENCE_IMPLEMENTATION_UNCONFIRMED",
    ]


def test_proposal_with_official_final_implementation_can_remain() -> None:
    decision = _decision(
        "The 2024 consultation was followed by this final rule, adopted and implemented. "
        "The regulation remains in force through 2027-12-31."
    )

    assert decision.promotable is True
    assert decision.status == "CURRENT_CONFIRMED"


def test_expired_event_without_ongoing_impact_is_blocked() -> None:
    decision = _decision(
        "The temporary street festival closure ended on 2025-05-04."
    )

    assert decision.promotable is False
    assert decision.reason_codes == [
        "REFERENCE_EXPIRED", "REFERENCE_NO_ONGOING_RELEVANCE"
    ]


def test_older_regulation_with_current_validity_is_allowed() -> None:
    decision = _decision(
        "Regulation published 2021-03-01 remains in force and continues to apply in 2026."
    )

    assert decision.promotable is True
    assert decision.status == "CURRENT_CONFIRMED"


def test_time_sensitive_claim_without_temporal_evidence_is_blocked() -> None:
    decision = _decision(
        "Official construction notice reports a temporary pedestrian route closure."
    )

    assert decision.promotable is False
    assert decision.status == "TEMPORAL_EVIDENCE_MISSING"
    assert decision.reason_codes == ["REFERENCE_NO_ONGOING_RELEVANCE"]


def test_superseded_reference_is_blocked_even_when_it_has_dates() -> None:
    decision = _decision(
        "This 2026-08-01 operating restriction was superseded by the revised notice."
    )

    assert decision.promotable is False
    assert decision.status == "SUPERSEDED"
    assert decision.reason_codes == ["REFERENCE_SUPERSEDED"]


def test_time_invariant_official_context_has_freshness_decision() -> None:
    decision = _decision(
        "Official census methodology defines the business-size classification used in the report."
    )

    assert decision.promotable is True
    assert decision.status == "CURRENT_OR_TIME_INVARIANT"
    assert decision.reason_codes == []
