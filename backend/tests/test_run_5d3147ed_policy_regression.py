"""Deterministic P0 policy-storage and semantic-validation regressions."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import PolicyCandidate
from src.storage import Database, PolicyRepository, SourceRepository
from src.storage.repositories import PolicyIdentityCollisionError
from src.validation.policy_identity import canonicalize_policy_identity
from src.validation.policy_validator import validate_policy_candidate
from tests.research_fixtures import source_document


def _policy(
    document,
    *,
    name: str = "Working capital support",
    supplied_id: str = "POL-EXTRACTOR-ID",
    quote: str | None = None,
    field_paths: list[str] | None = None,
    limit_krw: Decimal | None = Decimal("50000000"),
    budget_status: str = "AVAILABLE",
) -> PolicyCandidate:
    text = quote if quote is not None else document.body_text
    return PolicyCandidate(
        policy_candidate_id=supplied_id,
        research_run_id="RUN-5D3147ED-912",
        policy_type="LOAN_SUPPORT",
        name=name,
        provider_raw="Seoul City",
        limit_krw=limit_krw,
        budget_status=budget_status,
        source_ids=[document.source_id],
        evidence=[EvidenceRef(
            evidence_id=f"EVI-{name.replace(' ', '-')}",
            source_id=document.source_id,
            source_revision_id=document.revision_id,
            field_paths=field_paths or ["name"],
            quote=text,
            start_offset=document.body_text.index(text),
            end_offset=document.body_text.index(text) + len(text),
        )],
    )


def test_policy_fingerprints_are_deterministic_and_prevent_extractor_id_collisions(tmp_path) -> None:
    first_document = source_document(source_id="SRC-POLICY-ONE")
    second_document = source_document(source_id="SRC-POLICY-TWO", revision_id="REV-POLICY-TWO")
    first = canonicalize_policy_identity(_policy(first_document), {first_document.source_id: first_document})
    repeated = canonicalize_policy_identity(_policy(first_document), {first_document.source_id: first_document})
    second = canonicalize_policy_identity(
        _policy(second_document, name="Different emergency loan"),
        {second_document.source_id: second_document},
    )

    assert first.policy_candidate_id == repeated.policy_candidate_id
    assert first.identity_fingerprint == repeated.identity_fingerprint
    assert first.policy_candidate_id != second.policy_candidate_id
    assert first.extractor_policy_candidate_id == "POL-EXTRACTOR-ID"

    database = Database(f"sqlite:///{(tmp_path / 'policy.db').as_posix()}")
    database.migrate()
    sources = SourceRepository(database)
    sources.save(first_document, first.research_run_id)
    sources.save(second_document, second.research_run_id)
    repository = PolicyRepository(database)
    repository.save(first)
    repository.save(second)
    assert len(repository.list_for_run(first.research_run_id)) == 2

    conflicting = second.model_copy(update={"policy_candidate_id": first.policy_candidate_id})
    with pytest.raises(PolicyIdentityCollisionError):
        repository.save(conflicting)


def test_policy_evidence_semantics_prevent_false_full_validation() -> None:
    missing_limit_document = source_document(
        body="Program limit: KRW 50,000,000. Applications are open.",
        source_id="SRC-MISSING-LIMIT",
        revision_id="REV-MISSING-LIMIT",
    )
    missing_limit = _policy(
        missing_limit_document,
        quote="Program limit: KRW 50,000,000.",
        field_paths=["limit_krw"],
        limit_krw=None,
    )
    validated_missing = validate_policy_candidate(
        missing_limit, {missing_limit_document.source_id: missing_limit_document}, date(2026, 7, 30)
    )
    assert validated_missing.validation_status == "PARTIALLY_VALIDATED"
    assert "POLICY_FIELD_VALUE_MISSING" in validated_missing.validation_failure_codes

    closed_document = source_document(
        body="Applications are closed. Program limit: KRW 50,000,000.",
        source_id="SRC-CLOSED",
        revision_id="REV-CLOSED",
    )
    closed = _policy(closed_document, quote=closed_document.body_text, field_paths=["limit_krw"])
    validated_closed = validate_policy_candidate(
        closed, {closed_document.source_id: closed_document}, date(2026, 7, 30)
    )
    assert validated_closed.validation_status == "CLOSED"

    mismatched_document = source_document(
        body="Program limit: KRW 50,000,000.",
        source_id="SRC-MISMATCH",
        revision_id="REV-MISMATCH",
    )
    mismatched = _policy(
        mismatched_document,
        quote=mismatched_document.body_text,
        field_paths=["limit_krw"],
        limit_krw=Decimal("75000000"),
    )
    validated_mismatch = validate_policy_candidate(
        mismatched, {mismatched_document.source_id: mismatched_document}, date(2026, 7, 30)
    )
    assert validated_mismatch.validation_status == "PARTIALLY_VALIDATED"
    assert "POLICY_FIELD_EVIDENCE_MISMATCH" in validated_mismatch.validation_failure_codes


def test_policy_lifecycle_exposes_specific_non_recommendation_reasons() -> None:
    document = source_document(
        body="Official working capital support notice for small businesses.",
        source_id="SRC-LIFECYCLE",
        revision_id="REV-LIFECYCLE",
    )
    documents = {document.source_id: document}

    unconfirmed = validate_policy_candidate(
        _policy(document, budget_status="UNKNOWN"), documents, date(2026, 7, 30)
    )
    assert unconfirmed.validation_status == "VALIDATED"
    assert unconfirmed.application_status == "STATUS_UNCONFIRMED"
    assert unconfirmed.recommendation_failure_codes == [
        "POLICY_BUDGET_UNKNOWN",
        "POLICY_STATUS_UNCONFIRMED",
    ]

    exhausted = validate_policy_candidate(
        _policy(document, supplied_id="POL-EXHAUSTED", budget_status="EXHAUSTED"),
        documents,
        date(2026, 7, 30),
    )
    assert exhausted.validation_status == "VALIDATED"
    assert exhausted.application_status == "BUDGET_EXHAUSTED"
    assert exhausted.recommendation_failure_codes == ["POLICY_BUDGET_EXHAUSTED"]
