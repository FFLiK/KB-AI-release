"""Initial research-agent schema (frozen legacy table set)."""
from alembic import op

from src.storage.schema import metadata

revision = "0001_research_schema"
down_revision = None
branch_labels = None
depends_on = None

LEGACY_TABLES = {
    "research_runs", "search_queries", "search_results", "source_documents",
    "source_document_revisions", "model_call_records", "extraction_runs",
    "event_candidates", "event_evidence", "normalization_logs", "validation_logs",
    "canonical_events", "canonical_event_versions", "event_sources", "cause_groups",
    "store_signals", "policy_candidates", "policy_sources", "policy_validation_logs",
}


def upgrade():
    bind = op.get_bind()
    for table in metadata.sorted_tables:
        if table.name in LEGACY_TABLES:
            table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(metadata.sorted_tables):
        if table.name in LEGACY_TABLES:
            table.drop(bind=bind, checkfirst=True)
