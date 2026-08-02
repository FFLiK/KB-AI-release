from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update

from src.contracts.canonical_event import CanonicalEvent
from src.contracts.event_candidate import ExtractedEventCandidate
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import ModelCallRecord, ResearchRequest
from src.contracts.source_document import SourceDocument
from src.contracts.store_signal import StoreSignal
from src.storage.database import Database
from src.storage.schema import (canonical_event_versions, canonical_events, event_candidates,
    event_evidence, event_sources, model_call_records, normalization_logs, policy_candidates,
    policy_sources, research_runs, source_document_revisions, source_documents, validation_logs)
from src.storage.schema import (cause_groups, extraction_runs, search_queries, search_results,
    store_signals, policy_validation_logs)


def _audit(run_id: str | None, status: str, schema: str = "v1", producer: str = "backend") -> dict[str, Any]:
    return {"run_id": run_id, "created_at": datetime.now(UTC), "schema_version": schema, "registry_version": "event_types.v1", "producer": producer, "status": status}


class SourceRepository:
    def __init__(self, db: Database): self.db = db

    def save(self, document: SourceDocument, run_id: str | None = None) -> tuple[SourceDocument, bool]:
        with self.db.engine.begin() as conn:
            existing_fingerprint = conn.execute(
                select(source_document_revisions.c.snapshot_fingerprint).where(
                    source_document_revisions.c.revision_id == document.revision_id
                )
            ).scalar_one_or_none()
            if existing_fingerprint and existing_fingerprint != document.snapshot_fingerprint:
                material = f"{document.source_id}|{document.snapshot_fingerprint}".encode()
                document = document.model_copy(update={
                    "revision_id": "REV-" + hashlib.sha256(material).hexdigest()[:20].upper()
                })
            payload = document.model_dump(mode="json")
            known = conn.execute(select(source_document_revisions.c.revision_id).where(
                source_document_revisions.c.source_id == document.source_id,
                source_document_revisions.c.snapshot_fingerprint == document.snapshot_fingerprint)).scalar_one_or_none()
            if known:
                stored = self.get(document.source_id, known, connection=conn)
                return stored, False
            base = conn.execute(select(source_documents.c.source_id).where(source_documents.c.source_id == document.source_id)).scalar_one_or_none()
            if not base:
                conn.execute(insert(source_documents).values(source_id=document.source_id, canonical_url=document.canonical_url, latest_revision_id=document.revision_id, **_audit(run_id, "FETCHED", document.schema_version, "document_fetcher")))
            else:
                conn.execute(update(source_documents).where(source_documents.c.source_id == document.source_id).values(latest_revision_id=document.revision_id, status="FETCHED"))
            conn.execute(insert(source_document_revisions).values(revision_id=document.revision_id, source_id=document.source_id, body_sha256=document.body_sha256, snapshot_fingerprint=document.snapshot_fingerprint, document_json=payload, **_audit(run_id, str(document.access_status), document.schema_version, "document_fetcher")))
        return document, True

    def get(self, source_id: str, revision_id: str | None = None, connection=None) -> SourceDocument:
        def read(conn):
            rid = revision_id or conn.execute(select(source_documents.c.latest_revision_id).where(source_documents.c.source_id == source_id)).scalar_one()
            data = conn.execute(select(source_document_revisions.c.document_json).where(source_document_revisions.c.revision_id == rid)).scalar_one()
            return SourceDocument.model_validate(data)
        if connection is not None: return read(connection)
        with self.db.engine.connect() as conn: return read(conn)

    def list_revisions(self, source_id: str) -> list[str]:
        with self.db.engine.connect() as conn:
            return list(conn.execute(select(source_document_revisions.c.revision_id).where(source_document_revisions.c.source_id == source_id).order_by(source_document_revisions.c.created_at)).scalars())


class AuditRepository:
    def __init__(self, db: Database): self.db = db
    def create_run(self, request: ResearchRequest, status: str = "QUEUED") -> None:
        with self.db.engine.begin() as conn:
            conn.execute(insert(research_runs).values(id=request.run_id, request_json=request.model_dump(mode="json"), **_audit(request.run_id, status, "research_request.v1", "research_pipeline")))
    def update_run(self, run_id: str, status: str) -> None:
        with self.db.engine.begin() as conn: conn.execute(update(research_runs).where(research_runs.c.id == run_id).values(status=status, updated_at=datetime.now(UTC)))
    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.db.engine.connect() as conn:
            row = conn.execute(select(research_runs).where(research_runs.c.id == run_id)).mappings().one_or_none()
            return dict(row) if row else None
    def log_model_call(self, record: ModelCallRecord, run_id: str) -> None:
        with self.db.engine.begin() as conn: conn.execute(insert(model_call_records).values(id=record.call_id, record_json=record.model_dump(mode="json"), **_audit(run_id, record.validation_result, record.schema_version, record.provider)))
    def log_search(
        self, run_id: str, query_id: str, query: str, result: Any, request: Any | None = None
    ) -> None:
        raw_metadata = result.raw_metadata or {}
        ordered_hits = sorted(result.hits, key=lambda hit: (hit.rank, hit.url))
        metadata = {
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "retry_count": int(raw_metadata.get("retry_count") or 0),
            "provider_response_id": raw_metadata.get("response_id") or result.request_id,
            "allowed_domains": list(request.allowed_domains) if request is not None else [],
            "result_order": [hit.url for hit in ordered_hits],
        }
        query_status = "COMPLETED" if ordered_hits else "NO_RESULTS"
        with self.db.engine.begin() as conn:
            if not conn.execute(
                select(search_queries.c.id).where(search_queries.c.id == query_id)
            ).scalar_one_or_none():
                conn.execute(insert(search_queries).values(
                    id=query_id,
                    query=query,
                    metadata_json=metadata,
                    **_audit(run_id, query_status, "search_query.v1", result.provider),
                ))
            for hit in ordered_hits:
                hit_id = "SR-" + hashlib.sha256(
                    f"{query_id}|{hit.url}".encode()
                ).hexdigest()[:24]
                if not conn.execute(
                    select(search_results.c.id).where(search_results.c.id == hit_id)
                ).scalar_one_or_none():
                    conn.execute(insert(search_results).values(
                        id=hit_id,
                        query_id=query_id,
                        url=hit.url,
                        rank=hit.rank,
                        metadata_json=hit.model_dump(mode="json"),
                        **_audit(run_id, "DISCOVERED", "search_hit.v1", result.provider),
                    ))

    def log_search_failure(
        self, run_id: str, request: Any, error: Any, provider: str
    ) -> None:
        metadata = {
            "provider": provider,
            "model": "UNKNOWN",
            "latency_ms": getattr(error, "retry_latency_ms", 0),
            "retry_count": getattr(error, "retry_count", 0),
            "provider_response_id": None,
            "allowed_domains": list(request.allowed_domains),
            "result_order": [],
            "failure_code": error.code,
            "http_status": error.http_status,
        }
        with self.db.engine.begin() as conn:
            if not conn.execute(
                select(search_queries.c.id).where(search_queries.c.id == request.request_id)
            ).scalar_one_or_none():
                conn.execute(insert(search_queries).values(
                    id=request.request_id,
                    query=request.query,
                    metadata_json=metadata,
                    **_audit(run_id, "FAILED", "search_query.v1", provider),
                ))
    def log_extraction(self, run_id: str, extraction_id: str, revision_id: str, result: Any) -> None:
        with self.db.engine.begin() as conn:
            if not conn.execute(select(extraction_runs.c.id).where(extraction_runs.c.id == extraction_id)).scalar_one_or_none():
                conn.execute(insert(extraction_runs).values(id=extraction_id, source_revision_id=revision_id, metadata_json={"provider": result.provider, "model": result.model, "candidate_count": len(result.candidates), "latency_ms": result.latency_ms}, **_audit(run_id, "EXTRACTED", "extraction_run.v1", result.provider)))
    def log_validation(self, run_id: str, candidate_id: str, from_state: str, to_state: str, failure_code: str | None = None, detail: str = "") -> None:
        with self.db.engine.begin() as conn: conn.execute(insert(validation_logs).values(id=f"VAL-{uuid.uuid4().hex}", candidate_id=candidate_id, from_state=from_state, to_state=to_state, failure_code=failure_code, detail=detail, **_audit(run_id, to_state, "validation_log.v1", "validation_pipeline")))


class EventRepository:
    def __init__(self, db: Database): self.db = db
    def save_candidate(self, candidate: ExtractedEventCandidate) -> None:
        with self.db.engine.begin() as conn:
            exists = conn.execute(select(event_candidates.c.candidate_id).where(
                event_candidates.c.candidate_id == candidate.candidate_id)).scalar_one_or_none()
            if not exists:
                conn.execute(insert(event_candidates).values(
                    candidate_id=candidate.candidate_id,
                    candidate_json=candidate.model_dump(mode="json"),
                    **_audit(candidate.research_run_id, "EXTRACTED", "event_candidate.v1",
                             candidate.extraction_metadata.model)))
            for ev in candidate.evidence:
                exists = conn.execute(select(event_evidence.c.evidence_id).where(event_evidence.c.evidence_id == ev.evidence_id)).scalar_one_or_none()
                if not exists: conn.execute(insert(event_evidence).values(evidence_id=ev.evidence_id, candidate_id=candidate.candidate_id, evidence_json=ev.model_dump(mode="json"), **_audit(candidate.research_run_id, "EXTRACTED", "evidence.v1", "extractor")))
    def save_canonical(self, event: CanonicalEvent) -> None:
        version_id = "EVV-" + hashlib.sha256(event.model_dump_json().encode()).hexdigest()[:24]
        with self.db.engine.begin() as conn:
            exists = conn.execute(select(canonical_events.c.event_id).where(canonical_events.c.event_id == event.event_id)).scalar_one_or_none()
            if not exists: conn.execute(insert(canonical_events).values(event_id=event.event_id, latest_version_id=version_id, fingerprint=event.fingerprint, **_audit(event.research_run_id, event.validation_status, event.schema_version, "normalizer")))
            else: conn.execute(update(canonical_events).where(canonical_events.c.event_id == event.event_id).values(latest_version_id=version_id, status=event.validation_status))
            version_exists = conn.execute(select(canonical_event_versions.c.version_id).where(canonical_event_versions.c.version_id == version_id)).scalar_one_or_none()
            if not version_exists: conn.execute(insert(canonical_event_versions).values(version_id=version_id, event_id=event.event_id, event_json=event.model_dump(mode="json"), **_audit(event.research_run_id, event.validation_status, event.schema_version, "normalizer")))
            for sid, rid in zip(event.source_ids, event.source_revision_ids):
                link_id=f"{event.event_id}:{rid}"
                if not conn.execute(select(event_sources.c.id).where(event_sources.c.id == link_id)).scalar_one_or_none(): conn.execute(insert(event_sources).values(id=link_id, event_id=event.event_id, source_id=sid, revision_id=rid, **_audit(event.research_run_id, "LINKED", "event_source.v1", "normalizer")))
            for index, rec in enumerate(event.normalization_records):
                conn.execute(insert(normalization_logs).values(id=f"{version_id}:{index}", candidate_id=event.candidate_ids[0], log_json=rec.model_dump(mode="json"), **_audit(event.research_run_id, "NORMALIZED", "normalization_log.v1", rec.rule_id)))
            if event.cause_group_id and not conn.execute(select(cause_groups.c.id).where(cause_groups.c.id == event.cause_group_id)).scalar_one_or_none():
                conn.execute(insert(cause_groups).values(id=event.cause_group_id, cause_key=event.cause_group_id, metadata_json={"first_event_id": event.event_id}, **_audit(event.research_run_id, "ACTIVE", "cause_group.v1", "reconciler")))
    def list_events(self, run_id: str, accepted_only: bool = False) -> list[CanonicalEvent]:
        query = select(canonical_event_versions.c.event_json).where(canonical_event_versions.c.run_id == run_id)
        if accepted_only: query = query.where(canonical_event_versions.c.status == "ACCEPTED")
        with self.db.engine.connect() as conn: return [CanonicalEvent.model_validate(x) for x in conn.execute(query).scalars()]
    def save_signals(self, run_id: str, signals: list[StoreSignal]) -> None:
        with self.db.engine.begin() as conn:
            for signal in signals:
                if not conn.execute(select(store_signals.c.signal_id).where(store_signals.c.signal_id == signal.signal_id)).scalar_one_or_none():
                    conn.execute(insert(store_signals).values(signal_id=signal.signal_id, event_id=signal.event_id, store_id=signal.store_id, signal_json=signal.model_dump(mode="json"), **_audit(run_id, "CALCULATED", signal.calculation_version, "signal_builder")))



class PolicyIdentityCollisionError(RuntimeError):
    """Raised when one primary key is associated with distinct policy facts."""


class PolicyRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, policy: PolicyCandidate) -> None:
        payload = policy.model_dump(mode="json")
        with self.db.engine.begin() as conn:
            existing_json = conn.execute(
                select(policy_candidates.c.policy_json).where(
                    policy_candidates.c.policy_candidate_id == policy.policy_candidate_id
                )
            ).scalar_one_or_none()
            if existing_json is not None:
                existing = PolicyCandidate.model_validate(existing_json)
                if (
                    not policy.identity_fingerprint
                    or existing.identity_fingerprint != policy.identity_fingerprint
                ):
                    raise PolicyIdentityCollisionError(
                        f"policy ID collision for {policy.policy_candidate_id}"
                    )
                conn.execute(update(policy_candidates).where(
                    policy_candidates.c.policy_candidate_id == policy.policy_candidate_id
                ).values(
                    policy_json=payload,
                    status=policy.validation_status,
                    updated_at=datetime.now(UTC),
                ))
            else:
                conn.execute(insert(policy_candidates).values(
                    policy_candidate_id=policy.policy_candidate_id,
                    policy_json=payload,
                    **_audit(
                        policy.research_run_id,
                        policy.validation_status,
                        policy.schema_version,
                        "policy_extractor",
                    ),
                ))
            conn.execute(insert(policy_validation_logs).values(
                id=f"PV-{uuid.uuid4().hex}",
                policy_candidate_id=policy.policy_candidate_id,
                log_json={
                    "validation_status": policy.validation_status,
                    "supersedes": policy.supersedes_policy_candidate_id,
                    "identity_fingerprint": policy.identity_fingerprint,
                },
                **_audit(
                    policy.research_run_id,
                    policy.validation_status,
                    "policy_validation.v1",
                    "policy_validator",
                ),
            ))
            for sid in policy.source_ids:
                link = f"{policy.policy_candidate_id}:{sid}"
                if not conn.execute(select(policy_sources.c.id).where(
                    policy_sources.c.id == link
                )).scalar_one_or_none():
                    conn.execute(insert(policy_sources).values(
                        id=link,
                        policy_candidate_id=policy.policy_candidate_id,
                        source_id=sid,
                        **_audit(
                            policy.research_run_id, "LINKED", "policy_source.v1", "policy_extractor"
                        ),
                    ))

    def list_for_run(self, run_id: str) -> list[PolicyCandidate]:
        with self.db.engine.connect() as conn:
            payloads = conn.execute(select(policy_candidates.c.policy_json).where(
                policy_candidates.c.run_id == run_id
            )).scalars()
            return [PolicyCandidate.model_validate(payload) for payload in payloads]
