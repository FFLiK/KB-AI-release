"""Durable status and error repository for asynchronous analysis jobs."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update

from src.storage.database import Database
from src.storage.repositories import _audit
from src.storage.schema import analysis_jobs


class AnalysisJobRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, run_id: str, payload_hash: str, tenant_id: str = "default") -> None:
        with self.db.engine.begin() as conn:
            if conn.execute(select(analysis_jobs.c.job_id).where(
                analysis_jobs.c.job_id == run_id,
                analysis_jobs.c.tenant_id == tenant_id,
            )).scalar_one_or_none():
                return
            conn.execute(insert(analysis_jobs).values(
                job_id=run_id,
                tenant_id=tenant_id,
                payload_hash=payload_hash,
                error_json=None,
                updated_at=datetime.now(UTC),
                **_audit(run_id, "QUEUED", "analysis_job.v1", "api"),
            ))

    def update(
        self,
        run_id: str,
        status: str,
        error: dict[str, Any] | None = None,
        tenant_id: str = "default",
    ) -> None:
        with self.db.engine.begin() as conn:
            conn.execute(update(analysis_jobs).where(
                analysis_jobs.c.job_id == run_id,
                analysis_jobs.c.tenant_id == tenant_id,
            ).values(status=status, error_json=error, updated_at=datetime.now(UTC)))

    def get(self, run_id: str, tenant_id: str = "default") -> dict[str, Any] | None:
        with self.db.engine.connect() as conn:
            row = conn.execute(select(analysis_jobs).where(
                analysis_jobs.c.job_id == run_id,
                analysis_jobs.c.tenant_id == tenant_id,
            )).mappings().one_or_none()
        return dict(row) if row else None

