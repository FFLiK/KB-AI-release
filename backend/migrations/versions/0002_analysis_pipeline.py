"""Add versioned analysis pipeline artifacts."""
from alembic import op

from src.storage.schema import (
    analysis_results,
    analysis_sections,
    forecast_runs,
    official_data_vintages,
    official_observations,
    scenario_results,
)

revision = "0002_analysis_pipeline"
down_revision = "0001_research_schema"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in (
        official_data_vintages,
        official_observations,
        forecast_runs,
        scenario_results,
        analysis_results,
        analysis_sections,
    ):
        table.create(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in (
        analysis_sections,
        analysis_results,
        scenario_results,
        forecast_runs,
        official_observations,
        official_data_vintages,
    ):
        table.drop(bind=bind, checkfirst=True)
