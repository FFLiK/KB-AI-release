from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.contracts.official import OfficialDataRequest
from src.contracts.research import ResearchRequest, StoreLocation
from src.contracts.store import StoreProfile
from src.forecasting.pipeline import BaselineForecastPipeline
from src.orchestration.analysis_orchestrator import AnalysisOrchestrator
from src.orchestration.official_data_pipeline import FakeOfficialAdapter, OfficialDataPipeline
from src.orchestration.research_pipeline import ResearchPipeline
from src.storage import AuditRepository, Database, EventRepository, PolicyRepository, SourceRepository
from src.storage.analysis_repository import (
    AnalysisResultRepository,
    ForecastRepository,
    OfficialDataRepository,
    ScenarioResultRepository,
)
from src.validation.research_validator import ResearchEventValidator


STORE_FIXTURE_DIR = Path("tests/fixtures/stores")
OFFICIAL_FIXTURE = Path("tests/fixtures/official/offline_official_observations.json")
INDICATORS = (
    "USD_KRW",
    "BASE_RATE",
    "FOOD_PRICE_INDEX",
    "IMPORT_UNIT_PRICE_HS090111",
)


def load_store(name: str = "cafe_gangnam_24m.json") -> StoreProfile:
    return StoreProfile.model_validate_json((STORE_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def load_official_observations() -> list[dict[str, object]]:
    payload = json.loads(OFFICIAL_FIXTURE.read_text(encoding="utf-8"))
    return payload["observations"]


def official_requests(indicators: tuple[str, ...] = INDICATORS) -> list[OfficialDataRequest]:
    return [
        OfficialDataRequest(
            provider="REPLAY",
            indicator_id=indicator,
            required=True,
            max_age_days=90,
        )
        for indicator in indicators
    ]


def research_request(store: StoreProfile, run_id: str = "OFFLINE-E2E-001") -> ResearchRequest:
    return ResearchRequest(
        run_id=run_id,
        as_of_date=date(2026, 7, 31),
        forecast_start=date(2026, 8, 1),
        forecast_end=date(2027, 1, 31),
        store_profile_snapshot_id=f"SNAPSHOT-{store.store_id}",
        business_type_code=store.business_type_code,
        ingredient_categories=["COFFEE_BEAN"],
        store_location=StoreLocation(
            address=store.address,
            latitude=float(store.latitude) if store.latitude is not None else None,
            longitude=float(store.longitude) if store.longitude is not None else None,
            administrative_area="서울특별시 강남구",
        ),
        administrative_area_codes=["11680"],
        search_radius_m=1500,
    )


def build_orchestrator(
    runtime_dir: Path,
    observations: list[dict[str, object]] | None = None,
) -> tuple[AnalysisOrchestrator, Database]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    database = Database(f"sqlite:///{(runtime_dir / 'offline-e2e.db').as_posix()}")
    database.migrate()
    events = EventRepository(database)
    policies = PolicyRepository(database)
    audit = AuditRepository(database)
    research = ResearchPipeline(
        [],
        ResearchEventValidator(),
        events,
        policies,
        audit,
    )
    official = OfficialDataPipeline(
        {"REPLAY": FakeOfficialAdapter(observations or load_official_observations())},
        OfficialDataRepository(database),
    )
    orchestrator = AnalysisOrchestrator(
        research_pipeline=research,
        official_pipeline=official,
        forecast_pipeline=BaselineForecastPipeline(ForecastRepository(database), backtest_windows=1),
        result_repository=AnalysisResultRepository(database),
        scenario_repository=ScenarioResultRepository(database),
    )
    return orchestrator, database
