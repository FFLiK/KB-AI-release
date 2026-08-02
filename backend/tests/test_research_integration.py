from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app,set_services
from src.contracts.store import MonthlyCostDetail,MonthlyFixedCostDetail,MonthlyHistory,StoreProfile
from src.normalization.geo_normalizer import FakeGeocoder
from src.orchestration.factory import ResearchServices
from src.orchestration.integrated_pipeline import run_integrated_analysis
from src.orchestration.research_pipeline import ResearchPipeline
from src.providers.base import SearchHit
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.local_event.agent import LocalEventResearchAgent
from src.storage import AuditRepository,Database,EventRepository,PolicyRepository,SourceRepository
from src.validation.research_validator import ResearchEventValidator
from tests.research_fixtures import StaticFetcher,candidate,research_request,source_document


def store()->StoreProfile:
    return StoreProfile(store_id="STORE-1",business_type_code="FNB_CAFE",address="Gangnam Road",latitude=Decimal("37.5"),longitude=Decimal("127.0"),minimum_operating_cash_krw=Decimal("5000000"),current_cash_krw=Decimal("10000000"),forecast_horizon_months=2,monthly_history=[MonthlyHistory(month="2026-07",revenue_krw=Decimal("30000000"),variable_costs=MonthlyCostDetail(ingredients_krw=Decimal("9000000"),platform_fee_krw=Decimal("3000000"),payment_fee_krw=Decimal("600000")),fixed_costs=MonthlyFixedCostDetail(rent_krw=Decimal("4000000"),labor_krw=Decimal("7000000"),utilities_krw=Decimal("1000000"),other_krw=Decimal("500000")))])


def services_for(tmp_path:Path,run_id:str="RES-TEST")->ResearchServices:
    db=Database(f"sqlite:///{(tmp_path/'integration.db').as_posix()}"); db.migrate(); sources=SourceRepository(db); events=EventRepository(db); policies=PolicyRepository(db); audit=AuditRepository(db)
    doc=source_document(); item=candidate(doc); item.research_run_id=run_id
    agent=LocalEventResearchAgent(search=FakeSearchProvider(hits=[SearchHit(url=doc.canonical_url,title=doc.title,rank=1,source_type=doc.source_type)]),fetcher=StaticFetcher(doc),extractor=FakeEventExtractor({doc.source_id:[item]}),source_repo=sources,event_repo=events,audit_repo=audit)
    pipeline=ResearchPipeline([agent],ResearchEventValidator(geocoder=FakeGeocoder({})),events,policies,audit)
    return ResearchServices(db,pipeline,sources,events,policies,audit)


def test_end_to_end_fake_provider_to_financial_trace(tmp_path:Path):
    svc=services_for(tmp_path); result=run_integrated_analysis(store(),research_request(),svc.pipeline)
    assert len(result.research.accepted_events)==1 and result.signals
    assert result.adjustments["HIGH_IMPACT"].revenue_multiplier<Decimal("1")
    assert result.financial_results["HIGH_IMPACT"].monthly_cash_flows[0].revenue_cash_krw<result.financial_results["BASELINE"].monthly_cash_flows[0].revenue_cash_krw
    metadata=result.financial_results["HIGH_IMPACT"].metadata
    assert result.research.accepted_events[0].event_id in metadata["event_ids"]
    assert result.research.accepted_events[0].source_ids[0] in metadata["source_ids"]
    assert svc.events.list_events("RES-TEST",accepted_only=True)


def test_fastapi_sync_and_status_endpoints(tmp_path:Path):
    svc=services_for(tmp_path,run_id="RES-API"); set_services(svc); client=TestClient(app)
    request=research_request("RES-API")
    payload={"store_profile":store().model_dump(mode="json"),"research_request":request.model_dump(mode="json")}
    response=client.post("/v1/analysis/sync",json=payload)
    assert response.status_code==200, response.text
    data=response.json(); assert data["accepted_events"] and data["signals"]
    status_response=client.get("/v1/research/RES-API")
    assert status_response.status_code==200 and status_response.json()["status"]=="COMPLETED"
    events=client.get("/v1/events",params={"run_id":"RES-API"})
    assert events.status_code==200 and len(events.json())==1


def test_api_rejects_duplicate_run_id(tmp_path:Path):
    svc=services_for(tmp_path,run_id="RES-DUP"); set_services(svc); client=TestClient(app)
    request=research_request("RES-DUP"); svc.audit.create_run(request)
    payload={"store_profile":store().model_dump(mode="json"),"research_request":request.model_dump(mode="json")}
    assert client.post("/v1/analysis",json=payload).status_code==409


def test_fastapi_async_submission_reaches_completed_status(tmp_path:Path):
    svc=services_for(tmp_path,run_id="RES-ASYNC"); set_services(svc); client=TestClient(app)
    request=research_request("RES-ASYNC")
    payload={"store_profile":store().model_dump(mode="json"),"research_request":request.model_dump(mode="json")}
    submitted=client.post("/v1/analysis",json=payload)
    assert submitted.status_code==202 and submitted.json()["status_url"]=="/v1/research/RES-ASYNC"
    status_response=client.get("/v1/research/RES-ASYNC")
    assert status_response.status_code==200
