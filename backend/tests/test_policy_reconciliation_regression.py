from __future__ import annotations

from decimal import Decimal
import pytest

from src.contracts.analysis import PolicyResultBundle, PolicySearchContext
from src.validation.policy_validator import PolicyReconciler
from src.validation.policy_identity import canonicalize_policy_identity
from tests.test_run_5d3147ed_policy_regression import _policy
from tests.research_fixtures import source_document


def test_duplicate_policy_sources_reconcile_to_one_canonical_policy() -> None:
    first_document = source_document(source_id="SRC-POLICY-A")
    second_document = source_document(source_id="SRC-POLICY-B")
    first = canonicalize_policy_identity(
        _policy(first_document, name="Emergency working capital support"),
        {first_document.source_id: first_document},
    )
    second = canonicalize_policy_identity(
        _policy(second_document, name="Emergency working capital support"),
        {second_document.source_id: second_document},
    )

    reconciled = PolicyReconciler().reconcile([second, first])

    assert len(reconciled) == 1
    assert reconciled[0].source_ids == sorted([first_document.source_id, second_document.source_id])
    assert {item.source_id for item in reconciled[0].evidence} == {
        first_document.source_id, second_document.source_id,
    }


def test_conflicting_source_validation_cannot_promote_duplicate_as_validated() -> None:
    first_document = source_document(source_id="SRC-CONFLICT-A")
    second_document = source_document(source_id="SRC-CONFLICT-B")
    first = canonicalize_policy_identity(
        _policy(first_document), {first_document.source_id: first_document}
    ).model_copy(update={"validation_status": "VALIDATED"})
    second = canonicalize_policy_identity(
        _policy(second_document), {second_document.source_id: second_document}
    ).model_copy(update={
        "validation_status": "REJECTED",
        "validation_failure_codes": ["POLICY_FIELD_EVIDENCE_MISMATCH"],
    })

    reconciled = PolicyReconciler().reconcile([first, second])

    assert len(reconciled) == 1
    assert reconciled[0].validation_status == "CONFLICTED"
    assert "SOURCE_CONFLICT" in reconciled[0].validation_failure_codes
    assert [item["status"] for item in reconciled[0].source_validation_details] == [
        "VALIDATED", "REJECTED",
    ]


def test_policy_result_contract_rejects_duplicate_canonical_ids() -> None:
    document = source_document(source_id="SRC-CONTRACT-DUPLICATE")
    candidate = canonicalize_policy_identity(
        _policy(document), {document.source_id: document}
    )
    context = PolicySearchContext(
        business_type_code="FNB_CAFE", region_codes=["11680"]
    )

    with pytest.raises(ValueError, match="duplicate canonical policy IDs"):
        PolicyResultBundle(
            search_context=context,
            candidates=[candidate, candidate],
        )


def _guarantee_policy(document, *, name: str, supplied_id: str):
    candidate = _policy(
        document,
        name=name,
        supplied_id=supplied_id,
        limit_krw=Decimal("300000000"),
    ).model_copy(update={
        "policy_type": "CREDIT_GUARANTEE",
        "provider_raw": "\uc11c\uc6b8\uc2e0\uc6a9\ubcf4\uc99d\uc7ac\ub2e8",
        "purpose": ["\uc2e0\uc6a9\ubcf4\uc99d\uc73c\ub85c \uc6b4\uc804\uc790\uae08 \uc9c0\uc6d0"],
        "region_codes": ["11680"],
        "notice_kind": "PROGRAM_DESCRIPTION",
        "validation_status": "VALIDATED",
    })
    return canonicalize_policy_identity(
        candidate,
        {document.source_id: document},
    )


def test_semantic_name_variants_merge_with_all_source_provenance() -> None:
    first_document = source_document(
        source_id="SRC-GUARANTEE-PAGE",
        revision_id="REV-GUARANTEE-PAGE",
        body="2026 Gangnam credit-guarantee program offers up to KRW 300,000,000.",
    )
    second_document = source_document(
        source_id="SRC-BANK-COOPERATION",
        revision_id="REV-BANK-COOPERATION",
        body="2026 Gangnam special credit guarantee support offers up to KRW 300,000,000.",
    )
    first = _guarantee_policy(
        first_document,
        name="2026\ub144 \uac15\ub0a8\uad6c \uc2e0\uc6a9\ubcf4\uc99d\uc9c0\uc6d0",
        supplied_id="EXT-GUARANTEE-A",
    )
    second = _guarantee_policy(
        second_document,
        name="2026\ub144 \uac15\ub0a8\uad6c \ud2b9\ubcc4 \uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0",
        supplied_id="EXT-GUARANTEE-B",
    )

    reconciled = PolicyReconciler().reconcile(
        [second, first],
        {
            first_document.source_id: first_document,
            second_document.source_id: second_document,
        },
    )

    assert len(reconciled) == 1
    merged = reconciled[0]
    assert merged.source_ids == ["SRC-BANK-COOPERATION", "SRC-GUARANTEE-PAGE"]
    assert {item.source_id for item in merged.evidence} == set(merged.source_ids)
    assert merged.merged_policy_candidate_ids == [
        "EXT-GUARANTEE-A", "EXT-GUARANTEE-B"
    ]
    assert merged.policy_merge_group_id.startswith("PMG-")
    assert len(merged.source_validation_details) == 2


def test_semantic_reconciliation_does_not_merge_different_program_years() -> None:
    old_document = source_document(
        source_id="SRC-GUARANTEE-2025", revision_id="REV-GUARANTEE-2025",
        body="2025 Gangnam credit-guarantee program offers KRW 300,000,000.",
    )
    current_document = source_document(
        source_id="SRC-GUARANTEE-2026", revision_id="REV-GUARANTEE-2026",
        body="2026 Gangnam credit-guarantee program offers KRW 300,000,000.",
    )
    old = _guarantee_policy(
        old_document, name="2025\ub144 \uac15\ub0a8\uad6c \uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0",
        supplied_id="EXT-2025",
    )
    current = _guarantee_policy(
        current_document, name="2026\ub144 \uac15\ub0a8\uad6c \uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0",
        supplied_id="EXT-2026",
    )

    assert len(PolicyReconciler().reconcile([old, current])) == 2


def test_semantic_reconciliation_does_not_merge_material_term_changes() -> None:
    first_document = source_document(source_id="SRC-LIMIT-A", revision_id="REV-LIMIT-A")
    second_document = source_document(source_id="SRC-LIMIT-B", revision_id="REV-LIMIT-B")
    first = _guarantee_policy(
        first_document, name="\uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0", supplied_id="EXT-LIMIT-A",
    )
    second = _guarantee_policy(
        second_document, name="\ud2b9\ubcc4 \uc2e0\uc6a9\ubcf4\uc99d\uc9c0\uc6d0", supplied_id="EXT-LIMIT-B",
    ).model_copy(update={"limit_krw": Decimal("200000000")})

    assert len(PolicyReconciler().reconcile([first, second])) == 2


def test_active_and_closed_revisions_remain_separate() -> None:
    first_document = source_document(source_id="SRC-OPEN", revision_id="REV-OPEN")
    second_document = source_document(source_id="SRC-CLOSED", revision_id="REV-CLOSED")
    active = _guarantee_policy(
        first_document, name="\uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0", supplied_id="EXT-OPEN",
    ).model_copy(update={"application_status": "OPEN"})
    closed = _guarantee_policy(
        second_document, name="\uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0", supplied_id="EXT-CLOSED",
    ).model_copy(update={"application_status": "CLOSED"})

    assert len(PolicyReconciler().reconcile([active, closed])) == 2

def test_semantic_merge_preserves_strongest_consistent_field_evidence() -> None:
    sparse_document = source_document(
        source_id="SRC-SPARSE", revision_id="REV-SPARSE",
    )
    detailed_document = source_document(
        source_id="SRC-DETAILED", revision_id="REV-DETAILED",
    )
    sparse = _guarantee_policy(
        sparse_document, name="\uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0", supplied_id="EXT-SPARSE",
    ).model_copy(update={"policy_candidate_id": "POL-A", "limit_krw": None})
    detailed = _guarantee_policy(
        detailed_document, name="\ud2b9\ubcc4 \uc2e0\uc6a9\ubcf4\uc99d\uc9c0\uc6d0", supplied_id="EXT-DETAILED",
    ).model_copy(update={
        "policy_candidate_id": "POL-B",
        "limit_krw": Decimal("300000000"),
        "industry_inclusions_raw": ["FOOD_SERVICE"],
    })

    merged = PolicyReconciler().reconcile([sparse, detailed])[0]

    assert merged.limit_krw == Decimal("300000000")
    assert merged.industry_inclusions_raw == ["FOOD_SERVICE"]

def test_merged_revision_ids_include_program_year_from_source_evidence() -> None:
    documents = {
        source_id: source_document(
            source_id=source_id,
            revision_id="REV-" + source_id,
            body=f"{year} Gangnam credit-guarantee program offers KRW 300,000,000.",
        )
        for source_id, year in (
            ("SRC-2025-A", "2025"),
            ("SRC-2025-B", "2025"),
            ("SRC-2026-A", "2026"),
            ("SRC-2026-B", "2026"),
        )
    }
    policies = [
        _guarantee_policy(
            document,
            name="\uac15\ub0a8\uad6c \uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0",
            supplied_id="EXT-" + source_id,
        )
        for source_id, document in documents.items()
    ]

    reconciled = PolicyReconciler().reconcile(policies, documents)

    assert len(reconciled) == 2
    assert all(len(item.source_ids) == 2 for item in reconciled)
    assert len({item.policy_candidate_id for item in reconciled}) == 2


def test_semantic_reconciliation_does_not_merge_different_business_categories() -> None:
    food_document = source_document(
        source_id="SRC-FOOD", revision_id="REV-FOOD",
    )
    retail_document = source_document(
        source_id="SRC-RETAIL", revision_id="REV-RETAIL",
    )
    food = _guarantee_policy(
        food_document, name="\uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0", supplied_id="EXT-FOOD",
    ).model_copy(update={"industry_inclusions_raw": ["FOOD_SERVICE"]})
    retail = _guarantee_policy(
        retail_document, name="\uc2e0\uc6a9\ubcf4\uc99d \uc9c0\uc6d0", supplied_id="EXT-RETAIL",
    ).model_copy(update={"industry_inclusions_raw": ["RETAIL"]})

    assert len(PolicyReconciler().reconcile([food, retail])) == 2
