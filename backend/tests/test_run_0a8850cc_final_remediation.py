import hashlib
import json
from decimal import Decimal
from pathlib import Path

from src.source_snapshot.bok import parse_bok_decision
from src.validation.policy_identity import canonicalize_policy_identity
from src.validation.policy_validator import PolicyReconciler
from src.validation.reference_temporal import evaluate_reference_freshness
from tests.research_fixtures import research_request, source_document
from tests.test_run_5d3147ed_policy_regression import _policy


FIXTURE = Path(__file__).parent / "fixtures/replay/RUN-0A8850CC-B9A.remediation.v1.json"
FIXTURE_SHA256 = "819d92e1c483c00b96b84094b0715953c5d83fefa22925ec7b92074e7cba3e40"


def _load_fixture() -> dict:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    return json.loads(raw)


def _policy_from_fixture(item: dict, body: str):
    document = source_document(
        source_id=item["source_id"],
        revision_id="REV-" + item["source_id"],
        body=body,
    )
    policy = _policy(
        document,
        name=item["name"],
        supplied_id=item["candidate_id"],
        limit_krw=Decimal("300000000"),
    ).model_copy(update={
        "policy_type": "CREDIT_GUARANTEE",
        "provider_raw": "\uc11c\uc6b8\uc2e0\uc6a9\ubcf4\uc99d\uc7ac\ub2e8",
        "purpose": ["\uc2e0\uc6a9\ubcf4\uc99d\uc73c\ub85c \uc6b4\uc804\uc790\uae08 \uc9c0\uc6d0"],
        "region_codes": ["11680"],
        "notice_kind": "PROGRAM_DESCRIPTION",
        "validation_status": "VALIDATED",
    })
    return document, canonicalize_policy_identity(
        policy, {document.source_id: document}
    )


def test_fixture_preserves_run_0a_problem_outputs() -> None:
    payload = _load_fixture()
    baseline = payload["baseline_problem_outputs"]

    assert payload["run_id"] == "RUN-0A8850CC-B9A"
    assert baseline["bok_reference_rate_percent"] == "2.1"
    assert len(baseline["duplicate_policy_candidate_ids"]) == 2
    assert baseline["policy_candidate_count"] == 5
    assert baseline["expired_tariff_proposal_promoted"] is True
    assert baseline["financial_signal_count"] == 0


def test_run_0a_replay_produces_corrected_reference_policy_count_and_no_signal() -> None:
    payload = _load_fixture()
    expected = payload["expected_outputs"]

    bok = payload["bok_document"]
    bok_document = source_document(
        source_id=bok["source_id"],
        revision_id=bok["revision_id"],
        body=bok["body_text"],
    ).model_copy(update={
        "canonical_url": bok["canonical_url"],
        "title": bok["title"],
    })
    bok_assessment = parse_bok_decision(bok_document)
    assert bok_assessment.usable is True
    assert bok_assessment.facts is not None
    assert bok_assessment.facts.current_rate_percent == expected["bok_reference_rate_percent"]
    assert "2.1%" not in bok_assessment.facts.evidence_text

    policy_documents = {}
    duplicate_policies = []
    for item in payload["semantic_policy_duplicates"]:
        document, policy = _policy_from_fixture(
            item,
            f"2026 Gangnam credit-guarantee program {item['candidate_id']} offers KRW 300,000,000.",
        )
        policy_documents[document.source_id] = document
        duplicate_policies.append(policy)
    reconciled = PolicyReconciler().reconcile(
        duplicate_policies, policy_documents
    )
    assert len(reconciled) == 1
    assert len(reconciled[0].source_ids) == 2
    replay_policy_count = (
        payload["baseline_problem_outputs"]["policy_candidate_count"]
        - len(duplicate_policies)
        + len(reconciled)
    )
    assert replay_policy_count == expected["policy_candidate_count"]

    stale = payload["stale_reference"]
    stale_document = source_document(
        source_id=stale["source_id"], body=stale["body_text"]
    ).model_copy(update={"title": stale["title"]})
    freshness = evaluate_reference_freshness(
        research_request(payload["run_id"]),
        stale_document,
        reference_summary=stale["title"],
        evidence_text=stale["body_text"],
    )
    assert freshness.promotable is expected["expired_tariff_proposal_promoted"]
    assert "REFERENCE_STALE_PROPOSAL" in freshness.reason_codes
    assert expected["financial_signal_count"] == 0
