"""Add policy candidate update timestamp.

Revision ID: 0004_policy_candidate_updated_at
Revises: 0003_analysis_jobs
"""

import sqlalchemy as sa
from alembic import op


revision = "0004_policy_candidate_updated_at"
down_revision = "0003_analysis_jobs"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("policy_candidates")}
    if "updated_at" in columns:
        return
    with op.batch_alter_table("policy_candidates") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE policy_candidates SET updated_at = created_at WHERE updated_at IS NULL"
    )
    with op.batch_alter_table("policy_candidates") as batch:
        batch.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )


def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("policy_candidates")}
    if "updated_at" in columns:
        with op.batch_alter_table("policy_candidates") as batch:
            batch.drop_column("updated_at")
