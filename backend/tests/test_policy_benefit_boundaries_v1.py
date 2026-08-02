from decimal import Decimal

from src.contracts.analysis import PolicySearchContext
from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.store import StoreProfile
from src.relief.pipeline import _apply_funding_terms, _policy_schema
from tests.research_fixtures import source_document


def _candidate(**updates) -> PolicyCandidate:
    document = source_document()
    evidence = EvidenceRef(
        evidence_id="EVD-POLICY-FUNDING",
        source_id=document.source_id,
        source_revision_id=document.revision_id,
        field_paths=["limit_krw", "interest_terms", "repayment_terms"],
        quote=document.body_text,
        start_offset=0,
        end_offset=len(document.body_text),
    )
    values = {
        "policy_candidate_id": "POLICY-FUNDING",
        "research_run_id": "RUN-POLICY-FUNDING",
        "policy_type": "LOAN_SUPPORT",
        "name": "Working capital loan",
        "provider_raw": "Agency",
        "limit_krw": Decimal("1000000"),
        "interest_terms": {"annual_rate_percent": Decimal("6")},
        "repayment_terms": {
            "principal_grace_months": 3,
            "maturity_months": 12,
            "repayment_method": "AMORTIZING",
        },
        "source_ids": [document.source_id],
        "evidence": [evidence],
        "validation_status": "VALIDATED",
    }
    values.update(updates)
    return PolicyCandidate(**values)


def _context() -> PolicySearchContext:
    return PolicySearchContext(
        required_funding_krw=Decimal("600000"),
        business_type_code="FNB_CAFE",
        region_codes=["11"],
        purposes=["WORKING_CAPITAL"],
    )


def test_policy_loan_adds_only_funding_gap_and_its_repayment_obligation():
    candidate = _candidate()
    modified = StoreProfile(
        store_id="STORE-POLICY",
        address="Seoul",
        current_cash_krw=Decimal("100"),
        minimum_operating_cash_krw=Decimal("0"),
    )

    notes, grace_by_loan = _apply_funding_terms(
        modified, candidate, _policy_schema(candidate), _context()
    )

    assert modified.current_cash_krw == Decimal("600100")
    assert len(modified.loans) == 1
    assert modified.loans[0].principal_balance_krw == Decimal("600000")
    assert modified.loans[0].annual_interest_rate == Decimal("0.06")
    assert grace_by_loan == {"POLICY-POLICY-FUNDING": 3}
    assert "explicit rate" in notes[0]


def test_policy_loan_fails_closed_when_repayment_terms_are_incomplete():
    candidate = _candidate(repayment_terms={"principal_grace_months": 3})
    modified = StoreProfile(
        store_id="STORE-POLICY-INCOMPLETE",
        address="Seoul",
        current_cash_krw=Decimal("100"),
        minimum_operating_cash_krw=Decimal("0"),
    )

    notes, grace_by_loan = _apply_funding_terms(
        modified, candidate, _policy_schema(candidate), _context()
    )

    assert modified.current_cash_krw == Decimal("100")
    assert modified.loans == []
    assert grace_by_loan == {}
    assert "incomplete" in notes[0]
