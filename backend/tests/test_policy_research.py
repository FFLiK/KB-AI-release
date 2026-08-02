from datetime import date
from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import PolicyCandidate
from tests.research_fixtures import source_document


def test_policy_contract_never_contains_eligibility_decision():
    doc=source_document(); evidence=EvidenceRef(evidence_id="PE-1",source_id=doc.source_id,source_revision_id=doc.revision_id,field_paths=["name","application_end"],quote=doc.body_text,start_offset=0,end_offset=len(doc.body_text))
    policy=PolicyCandidate(policy_candidate_id="POL-C-1",research_run_id="RES-TEST",policy_type="LOAN_SUPPORT",name="Working capital support",provider_raw="Agency",application_end=date(2026,12,31),source_ids=[doc.source_id],evidence=[evidence])
    payload=policy.model_dump()
    assert "eligibility_status" not in payload and payload["validation_status"]=="EXTRACTED"
