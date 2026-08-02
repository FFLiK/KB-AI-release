"""Composition helpers for the versioned analysis pipeline."""
from __future__ import annotations

from decimal import Decimal
from src.config.settings import Settings

from src.forecasting.pipeline import BaselineForecastPipeline
from src.ingestion.official_api.customs import CustomsAdapter
from src.ingestion.official_api.ecos import ECOSAdapter
from src.ingestion.official_api.kosis import KOSISAdapter
from src.orchestration.analysis_orchestrator import AnalysisOrchestrator
from src.orchestration.official_data_pipeline import OfficialDataPipeline
from src.storage.analysis_repository import (
    AnalysisResultRepository,
    ForecastRepository,
    OfficialDataRepository,
    ScenarioResultRepository,
)


def build_analysis_orchestrator(research_services) -> AnalysisOrchestrator:
    db = research_services.database
    settings = Settings()
    official = OfficialDataPipeline(
        adapters={
            "ECOS": ECOSAdapter(),
            "KOSIS": KOSISAdapter(),
            "CUSTOMS": CustomsAdapter(),
        },
        repository=OfficialDataRepository(db),
    )
    return AnalysisOrchestrator(
        research_pipeline=research_services.pipeline,
        official_pipeline=official,
        forecast_pipeline=BaselineForecastPipeline(ForecastRepository(db), Decimal(settings.forecast_min_improvement), settings.forecast_backtest_windows),
        result_repository=AnalysisResultRepository(db),
        scenario_repository=ScenarioResultRepository(db),
    )
