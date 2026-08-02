from decimal import Decimal
from pathlib import Path

from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.source_document import SourceType
from src.orchestration.research_pipeline import ResearchPipeline
from src.providers.base import SearchHit
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.extraction.policy import FakePolicyExtractor
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.policy_regulation.agent import PolicyRegulationResearchAgent
from src.storage import AuditRepository,Database,EventRepository,PolicyRepository,SourceRepository
from src.validation.research_validator import ResearchEventValidator
from tests.research_fixtures import StaticFetcher,research_request,source_document


def run_policy_pipeline(tmp_path:Path,source_type:SourceType):
    run_id=f"RES-POL-{source_type.value}"
    doc=source_document().model_copy(update={"source_type":source_type})
    evidence=EvidenceRef(evidence_id=f"PE-{source_type.value}",source_id=doc.source_id,
        source_revision_id=doc.revision_id,field_paths=["name","limit_krw"],
        quote=doc.body_text,start_offset=0,end_offset=len(doc.body_text))
    policy=PolicyCandidate(policy_candidate_id=f"POL-{source_type.value}",research_run_id=run_id,
        policy_type="LOAN_SUPPORT",name="Working capital support",provider_raw="Seoul City",
        purpose=["WORKING_CAPITAL"],limit_krw=Decimal("10000000"),
        interest_terms={"rate_discount_percentage_points":"2"},budget_status="AVAILABLE",
        source_ids=[doc.source_id],evidence=[evidence])
    db=Database(f"sqlite:///{(tmp_path/(source_type.value+'.db')).as_posix()}"); db.migrate()
    sources=SourceRepository(db); events=EventRepository(db); policies=PolicyRepository(db); audit=AuditRepository(db)
    agent=PolicyRegulationResearchAgent(
        search=FakeSearchProvider(hits=[SearchHit(url=doc.canonical_url,rank=1)]),
        fetcher=StaticFetcher(doc),extractor=FakeEventExtractor(),source_repo=sources,
        event_repo=events,audit_repo=audit,policy_extractor=FakePolicyExtractor({doc.source_id:[policy]}),
        policy_repo=policies)
    pipeline=ResearchPipeline([agent],ResearchEventValidator(),events,policies,audit)
    return pipeline.run(research_request(run_id))


def test_policy_pipeline_validates_official_evidence_and_terms(tmp_path:Path):
    result=run_policy_pipeline(tmp_path,SourceType.OFFICIAL_LOCAL_GOV)
    assert result.policies[0].validation_status=="PARTIALLY_VALIDATED"
    assert result.policies[0].interest_terms.rate_discount_percentage_points==Decimal("2")


def test_policy_pipeline_rejects_unknown_source(tmp_path:Path):
    result=run_policy_pipeline(tmp_path,SourceType.OTHER)
    assert result.policies[0].validation_status=="REJECTED"
