"""Add durable asynchronous job status, errors and tenant result boundary."""
import sqlalchemy as sa
from alembic import op

from src.storage.schema import analysis_jobs

revision = "0003_analysis_jobs"
down_revision = "0002_analysis_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    analysis_jobs.create(bind=bind, checkfirst=True)
    result_columns = {column["name"] for column in sa.inspect(bind).get_columns("analysis_results")}
    if "tenant_id" not in result_columns:
        op.add_column(
            "analysis_results",
            sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
        )
        op.create_index(
            "ix_analysis_results_tenant_id", "analysis_results", ["tenant_id"], unique=False
        )


def downgrade():
    bind = op.get_bind()
    analysis_jobs.drop(bind=bind, checkfirst=True)
    result_columns = {column["name"] for column in sa.inspect(bind).get_columns("analysis_results")}
    if "tenant_id" in result_columns:
        op.drop_index("ix_analysis_results_tenant_id", table_name="analysis_results")
        op.drop_column("analysis_results", "tenant_id")

