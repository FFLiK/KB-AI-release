"""Network-free research replay backed by explicitly synthetic demo datasets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.config.settings import Settings
from src.contracts.event_candidate import (
    EvidenceRef,EventImpact,ExtractedEventCandidate,ExtractionMetadata,LocationRaw,TemporalRaw,
)
from src.contracts.research import ReasoningLevel
from src.contracts.source_document import (
    AccessStatus,DocumentPageType,SourceDocument,SourceRole,SourceTrustLevel,SourceType,
)
from src.providers.base import (
    DocumentFetcher,EventExtractor,ExtractionResult,SearchHit,SearchProvider,SearchRequest,SearchResultBundle,
)


class DemoDatasetError(ValueError):
    pass


def _root(settings: Settings) -> Path:
    return (settings.demo_dataset_root or Path(__file__).resolve().parents[3] / "demo").resolve()


def _read(path: Path, root: Path) -> dict[str, Any]:
    resolved=path.resolve()
    if not resolved.is_relative_to(root):
        raise DemoDatasetError("demo dataset path escapes DEMO_DATASET_ROOT")
    try:
        with resolved.open(encoding="utf-8") as handle: payload=json.load(handle)
    except (OSError,json.JSONDecodeError) as exc:
        raise DemoDatasetError(f"cannot read demo dataset: {resolved}") from exc
    if not isinstance(payload,dict): raise DemoDatasetError("demo dataset must be an object")
    return payload


def load_demo_dataset(settings: Settings) -> dict[str, Any]:
    if not settings.enable_demo_datasets:
        raise DemoDatasetError("demo_replay requires ENABLE_DEMO_DATASETS=1")
    if not settings.demo_dataset_id:
        raise DemoDatasetError("demo_replay requires DEMO_DATASET_ID")
    root=_root(settings); catalog=_read(root/"index.json",root)
    entry=next((x for x in catalog.get("datasets",[]) if x.get("dataset_id")==settings.demo_dataset_id),None)
    if not entry: raise DemoDatasetError(f"unknown DEMO_DATASET_ID: {settings.demo_dataset_id}")
    payload=_read(root/str(entry["file"]),root); disclaimer=payload.get("disclaimer") or {}
    if (payload.get("status")!="SYNTHETIC_DEMO_ONLY" or disclaimer.get("synthetic") is not True
            or disclaimer.get("network_fetch_allowed") is not False):
        raise DemoDatasetError("demo_replay accepts only network-disabled synthetic datasets")
    if payload.get("dataset_id")!=settings.demo_dataset_id:
        raise DemoDatasetError("catalog and dataset identifiers differ")
    return payload


_PROFILES={
    "OFFICIAL_LOCAL_GOV_STYLE":(SourceType.OFFICIAL_LOCAL_GOV,SourceTrustLevel.OFFICIAL_TRUSTED,SourceRole.LOCAL_GOVERNMENT),
    "OFFICIAL_TOURISM_STYLE":(SourceType.OFFICIAL_SECONDARY,SourceTrustLevel.OFFICIAL_TRUSTED,SourceRole.LOCAL_GOVERNMENT),
    "VERIFIED_MEDIA_STYLE":(SourceType.MAJOR_NEWS,SourceTrustLevel.VERIFIED_MEDIA,SourceRole.OTHER),
    "INDUSTRY_ASSOCIATION_STYLE":(SourceType.INDUSTRY_ASSOCIATION,SourceTrustLevel.INSTITUTIONAL_TRUSTED,SourceRole.OTHER),
    "REFERENCE_ONLY_STYLE":(SourceType.MAJOR_NEWS,SourceTrustLevel.VERIFIED_MEDIA,SourceRole.OTHER),
}


def _document(raw: dict[str,Any],dataset_id: str) -> SourceDocument:
    body=str(raw["body_text"]); profile=str(raw.get("demo_source_profile") or "")
    source_type,trust,role=_PROFILES.get(profile,(SourceType.OTHER,SourceTrustLevel.UNVERIFIED,SourceRole.OTHER))
    return SourceDocument(
        source_id=str(raw["source_id"]),canonical_url=str(raw["canonical_url"]),publisher=raw.get("publisher"),
        source_type=source_type,source_trust_level=trust,source_role=role,published_at=raw.get("published_at"),
        retrieved_at=raw["retrieved_at"],title=str(raw.get("title") or ""),body_text=body,
        body_sha256=hashlib.sha256(body.encode()).hexdigest(),access_status=AccessStatus.OK,http_status=200,
        content_type="text/plain",revision_id=str(raw["revision_id"]),page_type=DocumentPageType.EVENT_DETAIL_PAGE,
        classification_reasons=["SYNTHETIC_DEMO_ONLY",f"DEMO_SOURCE_PROFILE_{profile}"],
        original_url=str(raw["canonical_url"]),final_url_resolved=True,retrieval_reason_code="DEMO_REPLAY",
        http_metadata={"x-demo-dataset-id":dataset_id,"x-synthetic-demo":"true"},
    )


class DemoReplayCorpus:
    def __init__(self,settings: Settings):
        self.payload=load_demo_dataset(settings); self.dataset_id=str(self.payload["dataset_id"])
        self.documents={d.source_id:d for d in (_document(x,self.dataset_id) for x in self.payload["source_documents"])}
        self.by_url={d.canonical_url.rstrip("/"):d for d in self.documents.values()}
        accepted=(self.payload.get("expected_pipeline") or {}).get("accepted_events",[])
        self.target_domains={str(x["domain"]).upper() for x in accepted}
        types={str(x["event_type"]) for x in accepted}; self.query_markers=set()
        if "LOCAL_FESTIVAL" in types: self.query_markers.update({"축제","행사"})
        if "INGREDIENT_SHORTAGE" in types: self.query_markers.update({"수급","도매가격","원두","coffee_bean"})

    @staticmethod
    def domain(value: str) -> str:
        value=value.upper()
        return next((x for x in ("LOCAL","INDUSTRY","POLICY","MACRO") if x in value),value)


class DemoReplaySearchProvider(SearchProvider):
    def __init__(self,corpus: DemoReplayCorpus): self.corpus=corpus; self.settings=None

    def search(self,request: SearchRequest) -> SearchResultBundle:
        replay=self.corpus.payload["discovery_replay"]
        selected=(self.corpus.domain(request.domain) in self.corpus.target_domains and
                  any(x in request.query.casefold() for x in self.corpus.query_markers))
        hits=[]
        if selected:
            for raw in replay["ordered_results"]:
                document=self.corpus.documents.get(str(raw["source_id"]))
                if not document: continue
                hits.append(SearchHit(
                    url=document.canonical_url,title=document.title,snippet=document.body_text[:240],
                    publisher=document.publisher,published_at=document.published_at,source_type=document.source_type,
                    rank=int(raw["rank"]),allowed_domains=list(replay.get("allowed_domains") or []),
                    discovery_query=request.query,grounding_metadata={"dataset_id":self.corpus.dataset_id,"synthetic":True},
                ))
        return SearchResultBundle(
            request_id=request.request_id,provider="demo-replay",model="dataset-search-replay-v1",
            hits=hits[:request.max_results],raw_metadata={"dataset_id":self.corpus.dataset_id,"network_used":False},
            reason_codes=[] if hits else ["DEMO_QUERY_NOT_SELECTED"],
        )


class DemoReplayDocumentFetcher(DocumentFetcher):
    def __init__(self,corpus: DemoReplayCorpus): self.corpus=corpus

    def fetch(self,hit: SearchHit) -> SourceDocument:
        document=self.corpus.by_url.get(hit.url.rstrip("/"))
        if not document: raise DemoDatasetError(f"network disabled for URL outside replay: {hit.url}")
        return document.model_copy(deep=True)


class DemoReplayEventExtractor(EventExtractor):
    def __init__(self,corpus: DemoReplayCorpus):
        self.corpus=corpus
        self.runtime_documents: dict[str,dict[str,SourceDocument]]={}

    def _evidence(self,source_id: str,quote: str,index: int,paths: list[str],run_id: str) -> EvidenceRef:
        documents=self.runtime_documents.get(run_id,{})
        document=documents.get(source_id,self.corpus.documents[source_id]); start=document.body_text.find(quote)
        if start<0: raise DemoDatasetError(f"quote missing from {source_id}")
        material=f"{self.corpus.dataset_id}|{source_id}|{index}|{quote}"
        return EvidenceRef(
            evidence_id="EVI-DEMO-"+hashlib.sha256(material.encode()).hexdigest()[:16].upper(),
            source_id=source_id,source_revision_id=document.revision_id,field_paths=paths,
            quote=quote,start_offset=start,end_offset=start+len(quote),
        )

    def _candidate(self,raw: dict[str,Any],run_id: str,level: ReasoningLevel) -> ExtractedEventCandidate:
        source_ids=list(raw["source_ids"]); quotes=list(raw["evidence_quotes"])
        if len(source_ids)!=len(quotes): raise DemoDatasetError("source/evidence count differs")
        paths=["event_type","temporal.start_raw","temporal.end_raw","impacts[0].axis","impacts[0].direction","impacts[0].mechanism"]
        if raw["domain"]=="LOCAL": paths.append("location.address_raw")
        evidence=[self._evidence(source,quote,i,paths,run_id) for i,(source,quote) in enumerate(zip(source_ids,quotes),1)]
        impact=raw["impact"]; location=raw.get("location") or {}; suffix=hashlib.sha256(run_id.encode()).hexdigest()[:8].upper()
        return ExtractedEventCandidate(
            candidate_id=f"{raw['candidate_id']}-{suffix}",research_run_id=run_id,domain=raw["domain"],
            event_family=raw["event_family"],event_type=raw["event_type"],title=raw["title"],
            actor_org_raw=self.runtime_documents.get(run_id,{}).get(source_ids[0],self.corpus.documents[source_ids[0]]).publisher,target_subject_raw="카페 업종",
            temporal=TemporalRaw(**raw["temporal"]),location=LocationRaw(
                address_raw=location.get("address_raw"),area_raw=location.get("area_raw"),
                latitude=location.get("latitude"),longitude=location.get("longitude"),
            ),affected_industries_raw=["카페","커피","FNB"],impacts=[EventImpact(
                axis=impact["axis"],direction=impact["direction"],mechanism=impact["mechanism"],
                evidence_ids=[x.evidence_id for x in evidence],
            )],attributes={"synthetic_demo":True,"demo_dataset_id":self.corpus.dataset_id},evidence=evidence,
            extraction_metadata=ExtractionMetadata(
                model="dataset-event-replay-v1",prompt_version="demo_replay.v1",
                reasoning_level=getattr(level,"value",str(level)),
            ),
        )

    def extract(self,document: SourceDocument,research_run_id: str,domain: str,
                reasoning_level: ReasoningLevel,failure_codes: list[str]|None=None) -> ExtractionResult:
        runtime_documents=self.runtime_documents.setdefault(research_run_id,{})
        runtime_documents[document.source_id]=document
        expected=self.corpus.payload.get("expected_pipeline") or {}; normalized=self.corpus.domain(domain); candidates=[]
        for raw in expected.get("accepted_events",[]):
            sources=list(raw["source_ids"])
            if (sources and document.source_id in sources
                    and all(source_id in runtime_documents for source_id in sources)
                    and normalized==raw["domain"]):
                candidates.append(self._candidate(raw,research_run_id,reasoning_level))
        reference=next((x for x in expected.get("reference_findings",[]) if x["source_id"]==document.source_id),None)
        summary=None; evidence=[]; status="CANDIDATES_EXTRACTED" if candidates else "NO_DISCRETE_EVENT"; reasons=[]
        if not candidates and reference:
            reason=str(reference["reason_code"]); reasons=[reason]; summary=str(reference["summary_ko"])
            status=reason if reason in {"INSUFFICIENT_TEMPORAL_EVIDENCE","INSUFFICIENT_IMPACT_EVIDENCE"} else "REFERENCE_FINDINGS_ONLY"
            evidence=[self._evidence(document.source_id,document.body_text,1,["reference_summary"],research_run_id)]
        rejected=next((x for x in expected.get("rejected_candidates",[]) if x["source_id"]==document.source_id),None)
        if not candidates and not reference and rejected: reasons=list(rejected.get("failure_codes") or [])
        material=f"{research_run_id}|{document.revision_id}|{normalized}"
        return ExtractionResult(
            request_id="DEMO-EXT-"+hashlib.sha256(material.encode()).hexdigest()[:20].upper(),
            provider="demo-replay",model="dataset-event-replay-v1",candidates=candidates,
            raw_metadata={"dataset_id":self.corpus.dataset_id,"network_used":False,"validation_retry":bool(failure_codes)},
            document_status=status,reason_codes=reasons,reference_summary=summary,reference_evidence=evidence,
        )
