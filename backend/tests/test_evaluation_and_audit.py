from decimal import Decimal
from pathlib import Path

from sqlalchemy import func,select

from src.evaluation.research_evaluator import ResearchEvaluator
from src.extraction.cost_tracking import CostTracker,TokenRates
from src.validation.policy_validator import PolicyReconciler
from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import PolicyCandidate
from src.storage.schema import extraction_runs,model_call_records,search_queries,search_results,store_signals,validation_logs
from tests.research_fixtures import candidate,source_document
from tests.test_research_integration import services_for,store
from src.orchestration.integrated_pipeline import run_integrated_analysis
from tests.research_fixtures import research_request


def test_cost_tracker_uses_configurable_token_rates():
    tracker=CostTracker({"model":TokenRates(Decimal("2"),Decimal("8"),Decimal("1"))})
    assert tracker.estimate("model",1_000_000,500_000,100_000)==5.9

    cost, status = tracker.estimate_with_status("model", 1_000_000, 500_000, 100_000)
    assert cost == 5.9 and status == "ESTIMATED"
    assert CostTracker().estimate_with_status("unknown", 1, 1) == (
        None, "MODEL_RATE_NOT_CONFIGURED"
    )


def test_local_cloud_evaluation_contract_metrics():
    doc=source_document(); item=candidate(doc)
    metrics=ResearchEvaluator().evaluate([[item]],[[item]],[doc])
    assert metrics.schema_pass_rate==1 and metrics.event_presence_f1==1
    assert metrics.event_type_accuracy==1 and metrics.valid_evidence_rate==1 and metrics.unsupported_fact_rate==0


def test_policy_correction_and_termination_linking():
    doc=source_document(); ev=EvidenceRef(evidence_id="P-E",source_id=doc.source_id,source_revision_id=doc.revision_id,field_paths=["name"],quote=doc.body_text,start_offset=0,end_offset=len(doc.body_text))
    first=PolicyCandidate(policy_candidate_id="P1",research_run_id="R",policy_type="LOAN_SUPPORT",name="Support",provider_raw="Agency",source_ids=[doc.source_id],evidence=[ev])
    ended=PolicyCandidate(policy_candidate_id="P2",research_run_id="R",policy_type="LOAN_SUPPORT",name="Support",provider_raw="Agency",source_ids=[doc.source_id],evidence=[ev.model_copy(update={"evidence_id":"P-E2"})],notice_kind="TERMINATION")
    result=PolicyReconciler().reconcile([first,ended])
    assert result[1].supersedes_policy_candidate_id=="P1" and result[1].validation_status=="CLOSED"


def test_integration_persists_every_audit_layer(tmp_path:Path):
    svc=services_for(tmp_path); run_integrated_analysis(store(),research_request(),svc.pipeline)
    with svc.database.engine.connect() as conn:
        for table in (search_queries,search_results,model_call_records,extraction_runs,validation_logs,store_signals):
            assert conn.execute(select(func.count()).select_from(table)).scalar_one()>0, table.name
