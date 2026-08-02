from __future__ import annotations

from datetime import UTC,date,datetime

from src.contracts.event_candidate import EvidenceRef,EventImpact,ExtractedEventCandidate,ExtractionMetadata,LocationRaw,TemporalRaw
from src.contracts.research import ResearchRequest,StoreLocation
from src.contracts.source_document import AccessStatus,SourceDocument,SourceType
from src.providers.base import DocumentFetcher,SearchHit

BODY="Construction notice: pedestrian path partially closed from 2026-08-01 to 2026-09-15 near Gangnam Road."


def source_document(body:str=BODY,source_id:str="SRC-TEST",revision_id:str="REV-TEST",security_flags=None)->SourceDocument:
    import hashlib
    return SourceDocument(source_id=source_id,canonical_url=f"https://www.seoul.go.kr/{source_id}",publisher="Seoul City",source_type=SourceType.OFFICIAL_LOCAL_GOV,published_at=datetime(2026,7,20,tzinfo=UTC),retrieved_at=datetime(2026,7,21,tzinfo=UTC),title="Construction notice",body_text=body,body_sha256=hashlib.sha256(body.encode()).hexdigest(),access_status=AccessStatus.OK,http_status=200,content_type="text/html",revision_id=revision_id,security_flags=security_flags or [])


def candidate(source:SourceDocument|None=None,candidate_id:str="EVC-TEST",start:str="2026-08-01",end:str="2026-09-15",lat:float=37.5,lon:float=127.0)->ExtractedEventCandidate:
    source=source or source_document(); quote=source.body_text; evidence=EvidenceRef(evidence_id=f"EVD-{candidate_id}",source_id=source.source_id,source_revision_id=source.revision_id,field_paths=["event_type","temporal.start_raw","temporal.end_raw","impacts[0].mechanism"],quote=quote,start_offset=0,end_offset=len(quote))
    return ExtractedEventCandidate(candidate_id=candidate_id,research_run_id="RES-TEST",domain="LOCAL",event_family="ACCESSIBILITY",event_type="PEDESTRIAN_PARTIAL_CLOSURE",title="Partial pedestrian closure",actor_org_raw="Seoul City",target_subject_raw="Gangnam Road",temporal=TemporalRaw(start_raw=start,end_raw=end),location=LocationRaw(address_raw="Gangnam Road",latitude=lat,longitude=lon),affected_industries_raw=["FNB"],impacts=[EventImpact(axis="REVENUE_DEMAND",direction="DECREASE",mechanism="PEDESTRIAN_ACCESS_RESTRICTION",evidence_ids=[evidence.evidence_id])],attributes={"closure_scope":"PARTIAL"},evidence=[evidence],extraction_metadata=ExtractionMetadata(model="fake-extractor-v1",prompt_version="local_event_extract.v1"))


def research_request(run_id:str="RES-TEST",official=None)->ResearchRequest:
    return ResearchRequest(run_id=run_id,as_of_date=date(2026,7,21),forecast_start=date(2026,8,1),forecast_end=date(2026,9,30),store_profile_snapshot_id="STORE-SNAPSHOT-1",business_type_code="FNB_CAFE",store_location=StoreLocation(address="Gangnam Road",latitude=37.5,longitude=127.0,administrative_area="Seoul"),administrative_area_codes=["11"],search_radius_m=1500,official_indicator_snapshot_ids=official or [])


class StaticFetcher(DocumentFetcher):
    def __init__(self,document:SourceDocument): self.document=document
    def fetch(self,hit:SearchHit)->SourceDocument: return self.document
