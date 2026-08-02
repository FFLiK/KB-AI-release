from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, UniqueConstraint
from sqlalchemy.sql import func

metadata = MetaData()


def audit_columns():
    return [
        Column("run_id", String(64), nullable=True, index=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("schema_version", String(64), nullable=False, default="v1"),
        Column("registry_version", String(64), nullable=False, default="event_types.v1"),
        Column("producer", String(128), nullable=False, default="backend"),
        Column("status", String(64), nullable=False),
    ]


research_runs = Table(
    "research_runs", metadata,
    Column("id", String(64), primary_key=True), Column("request_json", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    *audit_columns(),
)
search_queries = Table("search_queries", metadata, Column("id", String(64), primary_key=True), Column("query", Text, nullable=False), Column("metadata_json", JSON, nullable=False), *audit_columns())
search_results = Table("search_results", metadata, Column("id", String(64), primary_key=True), Column("query_id", String(64), ForeignKey("search_queries.id")), Column("url", Text, nullable=False), Column("rank", Integer, nullable=False), Column("metadata_json", JSON, nullable=False), *audit_columns())
source_documents = Table("source_documents", metadata, Column("source_id", String(64), primary_key=True), Column("canonical_url", Text, nullable=False, unique=True), Column("latest_revision_id", String(64)), *audit_columns())
source_document_revisions = Table("source_document_revisions", metadata, Column("revision_id", String(64), primary_key=True), Column("source_id", String(64), ForeignKey("source_documents.source_id"), nullable=False), Column("body_sha256", String(64), nullable=False), Column("snapshot_fingerprint", String(64), nullable=False), Column("document_json", JSON, nullable=False), UniqueConstraint("source_id", "snapshot_fingerprint", name="uq_source_snapshot_fingerprint"), *audit_columns())
model_call_records = Table("model_call_records", metadata, Column("id", String(64), primary_key=True), Column("record_json", JSON, nullable=False), *audit_columns())
extraction_runs = Table("extraction_runs", metadata, Column("id", String(64), primary_key=True), Column("source_revision_id", String(64), ForeignKey("source_document_revisions.revision_id")), Column("metadata_json", JSON, nullable=False), *audit_columns())
event_candidates = Table("event_candidates", metadata, Column("candidate_id", String(64), primary_key=True), Column("candidate_json", JSON, nullable=False), *audit_columns())
event_evidence = Table("event_evidence", metadata, Column("evidence_id", String(64), primary_key=True), Column("candidate_id", String(64), ForeignKey("event_candidates.candidate_id")), Column("evidence_json", JSON, nullable=False), *audit_columns())
normalization_logs = Table("normalization_logs", metadata, Column("id", String(64), primary_key=True), Column("candidate_id", String(64)), Column("log_json", JSON, nullable=False), *audit_columns())
validation_logs = Table("validation_logs", metadata, Column("id", String(64), primary_key=True), Column("candidate_id", String(64)), Column("from_state", String(64)), Column("to_state", String(64), nullable=False), Column("failure_code", String(64)), Column("detail", Text), *audit_columns())
canonical_events = Table("canonical_events", metadata, Column("event_id", String(64), primary_key=True), Column("latest_version_id", String(64)), Column("fingerprint", String(64), nullable=False, index=True), *audit_columns())
canonical_event_versions = Table("canonical_event_versions", metadata, Column("version_id", String(64), primary_key=True), Column("event_id", String(64), ForeignKey("canonical_events.event_id")), Column("event_json", JSON, nullable=False), *audit_columns())
event_sources = Table("event_sources", metadata, Column("id", String(128), primary_key=True), Column("event_id", String(64), ForeignKey("canonical_events.event_id")), Column("source_id", String(64), ForeignKey("source_documents.source_id")), Column("revision_id", String(64), ForeignKey("source_document_revisions.revision_id")), *audit_columns())
cause_groups = Table("cause_groups", metadata, Column("id", String(64), primary_key=True), Column("cause_key", String(128), nullable=False), Column("metadata_json", JSON, nullable=False), *audit_columns())
store_signals = Table("store_signals", metadata, Column("signal_id", String(64), primary_key=True), Column("event_id", String(64), ForeignKey("canonical_events.event_id")), Column("store_id", String(64), nullable=False), Column("signal_json", JSON, nullable=False), *audit_columns())
policy_candidates = Table(
    "policy_candidates",
    metadata,
    Column("policy_candidate_id", String(64), primary_key=True),
    Column("policy_json", JSON, nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
    *audit_columns(),
)
policy_sources = Table("policy_sources", metadata, Column("id", String(128), primary_key=True), Column("policy_candidate_id", String(64), ForeignKey("policy_candidates.policy_candidate_id")), Column("source_id", String(64), ForeignKey("source_documents.source_id")), *audit_columns())
policy_validation_logs = Table("policy_validation_logs", metadata, Column("id", String(64), primary_key=True), Column("policy_candidate_id", String(64)), Column("log_json", JSON, nullable=False), *audit_columns())

# Versioned analysis pipeline persistence. JSON snapshots are immutable while the
# normalized index columns support status polling, trace lookup and retention.
official_data_vintages = Table(
    "official_data_vintages", metadata,
    Column("vintage_id", String(64), primary_key=True),
    Column("provider", String(64), nullable=False),
    Column("source_revision_id", String(64), nullable=False),
    Column("body_hash", String(64), nullable=False),
    Column("vintage_json", JSON, nullable=False),
    UniqueConstraint("provider", "source_revision_id", "body_hash", name="uq_official_vintage_revision"),
    *audit_columns(),
)
official_observations = Table(
    "official_observations", metadata,
    Column("observation_id", String(64), primary_key=True),
    Column("indicator_id", String(128), nullable=False, index=True),
    Column("vintage_id", String(64), ForeignKey("official_data_vintages.vintage_id"), nullable=False),
    Column("observation_json", JSON, nullable=False),
    *audit_columns(),
)
forecast_runs = Table(
    "forecast_runs", metadata,
    Column("forecast_id", String(64), primary_key=True),
    Column("target", String(64), nullable=False),
    Column("forecast_json", JSON, nullable=False),
    *audit_columns(),
)
scenario_results = Table(
    "scenario_results", metadata,
    Column("scenario_id", String(96), primary_key=True),
    Column("forecast_id", String(64), nullable=False),
    Column("adjustment_id", String(64), nullable=False),
    Column("result_json", JSON, nullable=False),
    *audit_columns(),
)
analysis_results = Table(
    "analysis_results", metadata,
    Column("result_id", String(64), primary_key=True),
    Column("result_version", Integer, nullable=False),
    Column("tenant_id", String(64), nullable=False, default="default", server_default="default", index=True),
    Column("idempotency_key", String(128), nullable=False),
    Column("deterministic_hash", String(64), nullable=False),
    Column("result_json", JSON, nullable=False),
    *audit_columns(),
    UniqueConstraint("run_id", "result_version", name="uq_analysis_result_version"),
    UniqueConstraint("tenant_id", "idempotency_key", name="uq_analysis_result_tenant_idempotency"),
)
analysis_sections = Table(
    "analysis_sections", metadata,
    Column("id", String(160), primary_key=True),
    Column("result_id", String(64), ForeignKey("analysis_results.result_id"), nullable=False),
    Column("section_name", String(64), nullable=False),
    Column("section_json", JSON, nullable=False),
    *audit_columns(),
)
analysis_jobs = Table(
    "analysis_jobs", metadata,
    Column("job_id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False, default="default", server_default="default", index=True),
    Column("payload_hash", String(64), nullable=False),
    Column("error_json", JSON, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    *audit_columns(),
)
