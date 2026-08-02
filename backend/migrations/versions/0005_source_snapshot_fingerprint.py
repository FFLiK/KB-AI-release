"""Use extraction-relevant snapshot identity for source revisions.

Revision ID: 0005_source_snapshot_fingerprint
Revises: 0004_policy_candidate_updated_at
"""

import json
import sqlalchemy as sa
from alembic import op

from src.contracts.source_document import SourceDocument


revision = "0005_source_snapshot_fingerprint"
down_revision = "0004_policy_candidate_updated_at"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        column["name"] for column in inspector.get_columns("source_document_revisions")
    }
    unique_names = {
        item["name"] for item in inspector.get_unique_constraints(
            "source_document_revisions"
        )
    }
    with op.batch_alter_table("source_document_revisions") as batch:
        if "snapshot_fingerprint" not in columns:
            batch.add_column(
                sa.Column("snapshot_fingerprint", sa.String(64), nullable=True)
            )
        if "uq_source_body_hash" in unique_names:
            batch.drop_constraint("uq_source_body_hash", type_="unique")
    rows = list(bind.execute(sa.text(
        "SELECT revision_id, document_json FROM source_document_revisions"
    )).mappings())
    for row in rows:
        raw_document = row["document_json"]
        document = SourceDocument.model_validate(json.loads(raw_document) if isinstance(raw_document, str) else raw_document)
        bind.execute(sa.text(
            "UPDATE source_document_revisions SET snapshot_fingerprint=:fingerprint "
            "WHERE revision_id=:revision_id"
        ), {
            "fingerprint": document.snapshot_fingerprint,
            "revision_id": row["revision_id"],
        })
    with op.batch_alter_table("source_document_revisions") as batch:
        batch.alter_column(
            "snapshot_fingerprint", existing_type=sa.String(64), nullable=False
        )
        if "uq_source_snapshot_fingerprint" not in unique_names:
            batch.create_unique_constraint(
                "uq_source_snapshot_fingerprint", ["source_id", "snapshot_fingerprint"]
            )


def downgrade():
    with op.batch_alter_table("source_document_revisions") as batch:
        batch.drop_constraint("uq_source_snapshot_fingerprint", type_="unique")
        batch.drop_column("snapshot_fingerprint")
