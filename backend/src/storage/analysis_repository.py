"""Repositories for versioned analysis, official-data and forecast artifacts."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, insert, select

from src.contracts.analysis import AnalysisResultV1
from src.contracts.forecast import BaselineForecastBundle
from src.contracts.official import CanonicalObservation, OfficialDataBundle, SourceVintage
from src.storage.database import Database
from src.storage.repositories import _audit
from src.storage.schema import (
    analysis_results,
    analysis_sections,
    forecast_runs,
    official_data_vintages,
    official_observations,
    scenario_results,
)


class AnalysisResultRepository:
    def __init__(self, db: Database):
        self.db = db

    def next_version(self, run_id: str, tenant_id: str = "default") -> int:
        with self.db.engine.connect() as conn:
            current = conn.execute(select(func.max(analysis_results.c.result_version)).where(
                analysis_results.c.run_id == run_id,
                analysis_results.c.tenant_id == tenant_id,
            )).scalar_one_or_none()
        return int(current or 0) + 1

    def get_by_idempotency_key(self, key: str, tenant_id: str = "default") -> AnalysisResultV1 | None:
        with self.db.engine.connect() as conn:
            payload = conn.execute(select(analysis_results.c.result_json).where(
                analysis_results.c.idempotency_key == key,
                analysis_results.c.tenant_id == tenant_id,
            )).scalar_one_or_none()
        return AnalysisResultV1.model_validate(payload) if payload else None

    def save(self, result: AnalysisResultV1) -> AnalysisResultV1:
        existing = self.get_by_idempotency_key(result.idempotency_key, result.tenant_id)
        if existing:
            return existing
        payload = result.model_dump(mode="json")
        with self.db.engine.begin() as conn:
            conn.execute(insert(analysis_results).values(
                result_id=result.result_id,
                result_version=result.result_version,
                tenant_id=result.tenant_id,
                idempotency_key=result.idempotency_key,
                deterministic_hash=result.deterministic_hash,
                result_json=payload,
                **_audit(result.run_id, str(result.status), result.schema_version, "analysis_orchestrator"),
            ))
            for section_name, section in result.sections.items():
                name = str(getattr(section_name, "value", section_name))
                conn.execute(insert(analysis_sections).values(
                    id=f"{result.result_id}:{name}",
                    result_id=result.result_id,
                    section_name=name,
                    section_json=section.model_dump(mode="json"),
                    **_audit(result.run_id, str(section.status), "analysis_section.v1", "analysis_orchestrator"),
                ))
        return result

    def get(
        self, run_id: str, version: int | None = None, tenant_id: str = "default"
    ) -> AnalysisResultV1 | None:
        query = select(analysis_results.c.result_json).where(
            analysis_results.c.run_id == run_id,
            analysis_results.c.tenant_id == tenant_id,
        )
        if version is not None:
            query = query.where(analysis_results.c.result_version == version)
        else:
            query = query.order_by(analysis_results.c.result_version.desc()).limit(1)
        with self.db.engine.connect() as conn:
            payload = conn.execute(query).scalar_one_or_none()
        return AnalysisResultV1.model_validate(payload) if payload else None


class OfficialDataRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_bundle(self, run_id: str, bundle: OfficialDataBundle) -> None:
        vintages = {item.vintage_id: item for item in bundle.source_vintages}
        with self.db.engine.begin() as conn:
            for vintage in vintages.values():
                exists = conn.execute(select(official_data_vintages.c.vintage_id).where(
                    official_data_vintages.c.vintage_id == vintage.vintage_id
                )).scalar_one_or_none()
                if not exists:
                    conn.execute(insert(official_data_vintages).values(
                        vintage_id=vintage.vintage_id,
                        provider=vintage.provider,
                        source_revision_id=vintage.source_revision_id,
                        body_hash=vintage.body_hash,
                        vintage_json=vintage.model_dump(mode="json"),
                        **_audit(run_id, "PERSISTED", "official_vintage.v1", vintage.provider),
                    ))
            for observation in bundle.observations:
                exists = conn.execute(select(official_observations.c.observation_id).where(
                    official_observations.c.observation_id == observation.observation_id
                )).scalar_one_or_none()
                if not exists:
                    conn.execute(insert(official_observations).values(
                        observation_id=observation.observation_id,
                        indicator_id=observation.indicator_id,
                        vintage_id=observation.vintage_id,
                        observation_json=observation.model_dump(mode="json"),
                        **_audit(run_id, str(observation.quality_status), "official_observation.v1", observation.source_id),
                    ))

    def get_source_vintage(
        self, source_id: str, source_revision_id: str | None = None
    ) -> SourceVintage | None:
        """Resolve an official numeric source through its immutable vintage."""
        query = select(official_data_vintages.c.vintage_json).order_by(
            official_data_vintages.c.created_at.desc()
        )
        if source_revision_id is not None:
            query = query.where(official_data_vintages.c.source_revision_id == source_revision_id)
        with self.db.engine.connect() as conn:
            payloads = conn.execute(query).scalars()
            for payload in payloads:
                vintage = SourceVintage.model_validate(payload)
                if vintage.source_id == source_id:
                    return vintage
        return None


class ForecastRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, run_id: str, bundle: BaselineForecastBundle) -> None:
        with self.db.engine.begin() as conn:
            if conn.execute(select(forecast_runs.c.forecast_id).where(
                forecast_runs.c.forecast_id == bundle.forecast_id
            )).scalar_one_or_none():
                return
            conn.execute(insert(forecast_runs).values(
                forecast_id=bundle.forecast_id,
                target=bundle.target,
                forecast_json=bundle.model_dump(mode="json"),
                **_audit(run_id, str(bundle.status), bundle.version, "baseline_forecast_pipeline"),
            ))


class ScenarioResultRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, run_id: str, scenario_id: str, forecast_id: str, adjustment_id: str, payload: dict[str, Any]) -> None:
        with self.db.engine.begin() as conn:
            if conn.execute(select(scenario_results.c.scenario_id).where(
                scenario_results.c.scenario_id == scenario_id
            )).scalar_one_or_none():
                return
            conn.execute(insert(scenario_results).values(
                scenario_id=scenario_id,
                forecast_id=forecast_id,
                adjustment_id=adjustment_id,
                result_json=payload,
                **_audit(run_id, "CALCULATED", "financial_scenario.v2", "financial_scenario_pipeline"),
            ))
