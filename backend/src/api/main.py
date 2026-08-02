from __future__ import annotations

import os
import threading
import logging
import uuid
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from src.contracts.analysis import AnalysisResultV1, analysis_payload_hash, canonical_json_hash
from src.contracts.attribution import (
    CandidateEvidenceResponse,
    CandidateEvidenceSource,
    RetryMetadata,
    ValidationFailureDetail,
)
from src.config.settings import Settings
from src.contracts.event_candidate import EvidenceRef, ExtractedEventCandidate
from src.contracts.financial import FinancialScenarioResult
from src.contracts.official import OfficialDataRequest
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import ResearchRequest
from src.contracts.scenario import MonthlyScenarioAdjustment, ScenarioAdjustmentV2
from src.contracts.store import StoreProfile
from src.finance.monthly_scenario import run_monthly_financial_scenario
from src.ingestion.user_input.parser import ParseResult, parse_and_validate_csv_input
from src.orchestration.analysis_orchestrator import AnalysisExecution, AnalysisOrchestrator
from src.orchestration.bootstrap import build_analysis_orchestrator
from src.orchestration.factory import ResearchServices, build_services
from src.orchestration.job_runner import InProcessJobRunner
from src.operations.metrics import metrics
from src.storage.job_repository import AnalysisJobRepository
from src.reporting.grounded_summary import build_grounded_summary
from src.storage.schema import (
    canonical_event_versions,
    event_candidates,
    policy_candidates,
    validation_logs,
)


def _status_value(value: object) -> str:
    """Return the public enum value without leaking Python's enum class name."""

    enum_value = getattr(value, "value", value)
    return str(enum_value)


class AnalysisJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_profile: StoreProfile
    research_request: ResearchRequest
    official_data_requests: list[OfficialDataRequest] = Field(default_factory=list)


class JobAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    status: str
    status_url: str
    result_url: str | None = None


class CsvRowsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict[str, Any]]


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_name: str = "WHAT_IF"
    revenue_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    variable_cost_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    fixed_cost_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    interest_rate_delta: Decimal = Decimal("0")


class AnalysisStatusResponse(BaseModel):
    """Canonical, refresh-safe representation of an asynchronous analysis job."""

    model_config = ConfigDict(extra="forbid")
    run_id: str
    status: str
    result_id: str | None = None
    result_version: int | None = None
    created_at: datetime
    updated_at: datetime
    error: dict[str, Any] | None = None


class WhatIfResponse(BaseModel):
    """Links an append-only What-if result to the immutable base result."""

    model_config = ConfigDict(extra="forbid")
    base_result_id: str
    base_result_version: int
    result_id: str
    result_version: int
    scenario: FinancialScenarioResult


class EventEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    source_ids: list[str]
    source_revision_ids: list[str]
    evidence: list[EvidenceRef]


class PolicyDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: PolicyCandidate


class GeocodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(min_length=1, max_length=500)


class GeocodeResponse(BaseModel):
    """Safe browser-facing result from the configured server-side map adapter."""

    model_config = ConfigDict(extra="forbid")
    address: str
    normalized_address: str | None = None
    geocode_status: str
    provider: str | None = None
    candidate_count: int | None = None
    match_type: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    reason: str | None = None
    provider_error_code: str | None = None
    providers_attempted: list[str] = Field(default_factory=list)
    failure_codes: list[str] = Field(default_factory=list)


app = FastAPI(
    title="KB AI Deterministic Analysis API",
    version="1.1.0",
    description="Versioned evidence-grounded research, forecast, finance and policy analysis",
)
origins = [item.strip() for item in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if item.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-API-Key", "X-Correlation-ID"],

    )

logger = logging.getLogger("kb_ai.api")

_services: ResearchServices | None = None
_orchestrator: AnalysisOrchestrator | None = None
_runner: InProcessJobRunner | None = None
_errors: dict[str, str] = {}
_lock = threading.Lock()
_rate_windows: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def correlation_and_access_log(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or f"COR-{uuid.uuid4().hex}"
    request.state.correlation_id = correlation_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    metrics.observe("http_request_latency_ms", latency_ms)
    metrics.increment(f"http_status_{response.status_code}_total")
    logger.info(
        "request completed",
        extra={
            "correlation_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
        },
    )
    return response


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "0"))
    if limit > 0:
        identity = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = _rate_windows[identity]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        window.append(now)
    return await call_next(request)


def require_auth(x_api_key: str | None = Header(default=None)) -> None:
    mode = os.getenv("API_AUTH_MODE", "none").lower()
    if mode == "none":
        return
    expected = os.getenv("API_AUTH_KEY")
    if mode != "api_key" or not expected:
        raise HTTPException(status_code=503, detail="API authentication is not configured")
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid API key")


def services() -> ResearchServices:
    global _services
    if _services is None:
        _services = build_services(force_fake=os.getenv("RESEARCH_PROVIDER_MODE", "").lower() == "fake")
    return _services


def analysis_orchestrator() -> AnalysisOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = build_analysis_orchestrator(services())
    return _orchestrator


def job_runner() -> InProcessJobRunner:
    global _runner
    if _runner is None:
        mode = os.getenv("JOB_RUNNER_MODE", "in_process").lower()
        if mode not in {"in_process", "in-process"}:
            raise RuntimeError("Only in_process runner is available without an external Celery deployment")
        _runner = InProcessJobRunner(
            timeout_seconds=Settings().analysis_job_timeout_seconds
        )
    return _runner

def analysis_job_repository() -> AnalysisJobRepository:
    return AnalysisJobRepository(services().database)



def set_services(value: ResearchServices) -> None:
    global _services, _orchestrator, _runner
    _services = value
    _orchestrator = None
    _runner = None
    with _lock:
        _errors.clear()


def _idempotency(job: AnalysisJobRequest, header_value: str | None) -> str:
    return header_value or canonical_json_hash(job.model_dump(mode="json"))


def _execute(job: AnalysisJobRequest, idempotency_key: str) -> None:
    run_id = job.research_request.run_id
    analysis_job_repository().update(run_id, "RUNNING", tenant_id=job.research_request.tenant_id)
    try:
        execution = analysis_orchestrator().run(
            job.store_profile,
            job.research_request,
            job.official_data_requests,
            idempotency_key,
        )
        analysis_job_repository().update(run_id, _status_value(execution.result.status), tenant_id=job.research_request.tenant_id)
    except Exception as exc:
        services().audit.update_run(run_id, "FAILED")
        error_payload = {
            "type": type(exc).__name__,
            "message": str(exc),
            "retryable": False,
        }
        metrics.increment("analysis_failed_total")
        analysis_job_repository().update(run_id, "FAILED", error_payload, job.research_request.tenant_id)
        with _lock:
            _errors[run_id] = f"{type(exc).__name__}: {exc}"


def _check_submission(job: AnalysisJobRequest, idempotency_key: str) -> AnalysisResultV1 | None:
    if job.research_request.tenant_id != "default":
        raise HTTPException(status_code=400, detail="MVP supports only tenant_id=default")
    orchestrator = analysis_orchestrator()
    existing = orchestrator.result_repository.get_by_idempotency_key(idempotency_key, job.research_request.tenant_id)
    if existing:
        if existing.run_id != job.research_request.run_id:
            raise HTTPException(status_code=409, detail="idempotency key belongs to another run")
        return existing
    row = services().audit.get_run(job.research_request.run_id)
    if row:
        raise HTTPException(status_code=409, detail="run_id already exists with different payload")
    services().audit.create_run(job.research_request, "QUEUED")
    analysis_job_repository().create(job.research_request.run_id, idempotency_key, job.research_request.tenant_id)
    return None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> dict[str, str]:
    try:
        app_env = os.getenv("APP_ENV", "development").lower()
        if app_env == "production" and os.getenv("API_AUTH_MODE", "none").lower() == "none":
            raise RuntimeError("production requires API authentication")
        if app_env == "production" and os.getenv("JOB_RUNNER_MODE", "in_process").lower() in {"in_process", "in-process"}:
            raise RuntimeError("production requires an external durable job runner")
        tenant_mode = os.getenv("TENANT_MODE", "single").lower()
        if tenant_mode != "single":
            raise RuntimeError("multi-tenant isolation is not configured; TENANT_MODE must remain single")
        with services().database.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        runner_status = "ok" if job_runner() else "unavailable"
        return {"status": "ready", "database": "ok", "queue": runner_status}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"not ready: {exc}") from exc


@app.get("/internal/metrics", dependencies=[Depends(require_auth)])
def internal_metrics() -> dict[str, object]:
    return metrics.snapshot()


@app.post("/v1/analyses", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_auth)])
def submit_analysis_v1(job: AnalysisJobRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128)) -> JobAccepted:
    key = _idempotency(job, idempotency_key)
    existing = _check_submission(job, key)
    run_id = job.research_request.run_id
    if not existing:
        job_runner().submit(run_id, lambda: _execute(job, key))
    terminal = _status_value(existing.status) if existing else "QUEUED"
    return JobAccepted(
        run_id=run_id,
        status=terminal,
        status_url=f"/v1/analyses/{run_id}",
        result_url=f"/v1/analyses/{run_id}/result",
    )


@app.post("/v1/analyses/sync", response_model=AnalysisResultV1, dependencies=[Depends(require_auth)])
def run_analysis_sync_v1(job: AnalysisJobRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128)) -> AnalysisResultV1:
    key = _idempotency(job, idempotency_key)
    existing = _check_submission(job, key)
    if existing:
        return existing
    run_id = job.research_request.run_id
    analysis_job_repository().update(run_id, "RUNNING", tenant_id=job.research_request.tenant_id)
    try:
        result = analysis_orchestrator().run(
            job.store_profile, job.research_request, job.official_data_requests, key
        ).result
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc), "retryable": False}
        metrics.increment("analysis_failed_total")
        analysis_job_repository().update(run_id, "FAILED", error, job.research_request.tenant_id)
        services().audit.update_run(run_id, "FAILED")
        raise
    analysis_job_repository().update(run_id, _status_value(result.status), tenant_id=job.research_request.tenant_id)
    return result


@app.get("/v1/analyses/{run_id}", response_model=AnalysisStatusResponse, dependencies=[Depends(require_auth)])
def get_analysis(run_id: str) -> AnalysisStatusResponse:
    row = services().audit.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    result = analysis_orchestrator().result_repository.get(run_id)
    job = analysis_job_repository().get(run_id)
    return AnalysisStatusResponse(
        run_id=run_id,
        status=_status_value(result.status) if result else (job["status"] if job else row["status"]),
        result_id=result.result_id if result else None,
        result_version=result.result_version if result else None,
        created_at=row["created_at"],
        updated_at=job["updated_at"] if job else row["updated_at"],
        error=job["error_json"] if job else None,
    )


@app.get("/v1/analyses/{run_id}/result", response_model=AnalysisResultV1, dependencies=[Depends(require_auth)])
def get_analysis_result(run_id: str, version: int | None = None) -> AnalysisResultV1:
    result = analysis_orchestrator().result_repository.get(run_id, version)
    if not result:
        raise HTTPException(status_code=404, detail="analysis result not found")
    return result


@app.post("/v1/inputs/csv/validate", response_model=ParseResult, dependencies=[Depends(require_auth)])
def validate_csv_input(request: CsvRowsRequest) -> ParseResult:
    return parse_and_validate_csv_input(request.rows)


@app.get("/v1/events/{event_id}/evidence", response_model=EventEvidenceResponse, dependencies=[Depends(require_auth)])
def get_event_evidence(event_id: str) -> EventEvidenceResponse:
    with services().database.engine.connect() as conn:
        payload = conn.execute(
            select(canonical_event_versions.c.event_json)
            .where(canonical_event_versions.c.event_id == event_id)
            .order_by(canonical_event_versions.c.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    if not payload:
        raise HTTPException(status_code=404, detail="event not found")
    return EventEvidenceResponse(
        event_id=event_id,
        source_ids=payload.get("source_ids", []),
        source_revision_ids=payload.get("source_revision_ids", []),
        evidence=payload.get("evidence", []),
    )


@app.get(
    "/v1/event-candidates/{candidate_id}/evidence",
    response_model=CandidateEvidenceResponse,
    dependencies=[Depends(require_auth)],
)
def get_candidate_evidence(candidate_id: str) -> CandidateEvidenceResponse:
    with services().database.engine.connect() as conn:
        payload = conn.execute(
            select(event_candidates.c.candidate_json)
            .where(event_candidates.c.candidate_id == candidate_id)
        ).scalar_one_or_none()
        validation = conn.execute(
            select(validation_logs)
            .where(validation_logs.c.candidate_id == candidate_id)
            .order_by(validation_logs.c.created_at)
        ).mappings().all()
    if not payload:
        raise HTTPException(status_code=404, detail="event candidate not found")

    candidate = ExtractedEventCandidate.model_validate(payload)
    status_value = str(validation[-1]["to_state"]) if validation else "EXTRACTED"
    failure_codes = sorted({str(row["failure_code"]) for row in validation if row["failure_code"]})
    failure_details = [
        ValidationFailureDetail(
            code=code,
            message=code.replace("_", " ").title(),
            retryable=status_value == "RETRYABLE",
        )
        for code in failure_codes
    ]
    retry = RetryMetadata()
    result = analysis_orchestrator().result_repository.get(candidate.research_run_id)
    if result:
        summary = next(
            (item for item in result.research.rejected_events if item.candidate_id == candidate_id),
            None,
        )
        if summary:
            status_value = summary.status
            failure_codes = summary.failure_codes
            failure_details = summary.failure_details
            retry = summary.retry

    sources: list[CandidateEvidenceSource] = []
    for evidence in candidate.evidence:
        if any(item.source_revision_id == evidence.source_revision_id for item in sources):
            continue
        try:
            document = services().sources.get(evidence.source_id, evidence.source_revision_id)
        except Exception:
            continue
        sources.append(CandidateEvidenceSource(
            source_id=document.source_id,
            source_revision_id=document.revision_id,
            title=document.title,
            publisher=document.publisher,
            canonical_url=document.canonical_url,
            retrieved_at=document.retrieved_at,
            access_status=str(document.access_status),
            http_status=document.http_status,
            content_type=document.content_type,
        ))
    return CandidateEvidenceResponse(
        candidate_id=candidate_id,
        validation_status=status_value,
        failure_codes=failure_codes,
        failure_details=failure_details,
        evidence=candidate.evidence,
        sources=sources,
        retry=retry,
    )




@app.get("/v1/policies/{policy_id}", response_model=PolicyDetailResponse, dependencies=[Depends(require_auth)])
def get_policy(policy_id: str) -> PolicyDetailResponse:
    with services().database.engine.connect() as conn:
        payload = conn.execute(select(policy_candidates.c.policy_json).where(
            policy_candidates.c.policy_candidate_id == policy_id
        )).scalar_one_or_none()
    if not payload:
        raise HTTPException(status_code=404, detail="policy not found")
    return PolicyDetailResponse(policy=PolicyCandidate.model_validate(payload))


@app.post("/v1/analyses/{run_id}/what-if", response_model=WhatIfResponse, dependencies=[Depends(require_auth)])
def run_what_if(run_id: str, request: WhatIfRequest) -> WhatIfResponse:
    repository = analysis_orchestrator().result_repository
    result = repository.get(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="analysis result not found")
    if not result.baseline.monthly_forecasts:
        raise HTTPException(status_code=409, detail="baseline forecast is unavailable")

    request_hash = canonical_json_hash(request)
    idempotency_key = f"what-if:{result.result_id}:{request_hash}"
    existing = repository.get_by_idempotency_key(idempotency_key)
    if existing:
        saved_scenario = existing.scenarios[request.scenario_name]
        return WhatIfResponse(
            base_result_id=result.result_id,
            base_result_version=result.result_version,
            result_id=existing.result_id,
            result_version=existing.result_version,
            scenario=saved_scenario,
        )

    store = StoreProfile.model_validate(result.input_snapshot["store_profile"])
    months = [MonthlyScenarioAdjustment(
        month=item.month,
        revenue_multiplier=request.revenue_multiplier,
        variable_cost_multiplier=request.variable_cost_multiplier,
        fixed_cost_multiplier=request.fixed_cost_multiplier,
        interest_rate_delta=request.interest_rate_delta,
    ) for item in result.baseline.monthly_forecasts]
    adjustment = ScenarioAdjustmentV2(
        adjustment_id="ADJ-WHATIF-" + request_hash[:16].upper(),
        scenario=request.scenario_name,
        months=months,
        source_ids=[],
        coefficient_version="user_what_if.v1",
    )
    scenario = run_monthly_financial_scenario(
        store, result.baseline, adjustment, official_features=result.official_features
    )
    scenario_id = f"SCN-{result.baseline.forecast_id}-{adjustment.adjustment_id}"
    scenario.metadata["scenario_id"] = scenario_id
    analysis_orchestrator().scenario_repository.save(
        run_id, scenario_id, result.baseline.forecast_id,
        adjustment.adjustment_id, scenario.model_dump(mode="json"),
    )

    derived = result.model_copy(deep=True)
    derived.result_version = repository.next_version(run_id)
    derived.result_id = f"AR-{run_id}-V{derived.result_version}"
    derived.idempotency_key = idempotency_key
    derived.created_at = datetime.now(UTC)
    derived.completed_at = derived.created_at
    derived.adjustments[request.scenario_name] = adjustment
    derived.scenarios[request.scenario_name] = scenario
    derived.traceability.scenario_ids = sorted(set(
        [*derived.traceability.scenario_ids, scenario_id]
    ))
    derived.traceability.calculation_result_ids = sorted(set(
        [*derived.traceability.calculation_result_ids, scenario_id]
    ))
    derived.grounded_summary = build_grounded_summary(
        derived.result_id, derived.baseline, derived.scenarios, derived.traceability
    )
    derived.deterministic_hash = analysis_payload_hash(derived)
    saved = repository.save(derived)
    return WhatIfResponse(
        base_result_id=result.result_id,
        base_result_version=result.result_version,
        result_id=saved.result_id,
        result_version=saved.result_version,
        scenario=saved.scenarios[request.scenario_name],
    )


@app.post("/v1/locations/geocode", response_model=GeocodeResponse, dependencies=[Depends(require_auth)])
def geocode_location(request: GeocodeRequest) -> GeocodeResponse:
    """Geocode an address server-side without exposing a provider credential to a browser."""
    from src.ingestion.official_api.map_api import MapApiAdapter
    from src.normalization.address_normalizer import normalize_korean_address

    normalized = normalize_korean_address(request.address)
    if os.getenv("RESEARCH_PROVIDER_MODE", "").lower() == "fake":
        demo_addresses = {
            "서울특별시 강남구 테헤란로 152": (Decimal("37.500950"), Decimal("127.036510")),
            "서울특별시 강남구 테헤란로 123": (Decimal("37.497900"), Decimal("127.027600")),
        }
        coordinates = demo_addresses.get(normalized)
        if coordinates:
            return GeocodeResponse(
                address=request.address, normalized_address=normalized, geocode_status="SUCCESS",
                provider="DETERMINISTIC_FIXTURE", candidate_count=1, match_type="EXACT_ROAD_ADDRESS",
                latitude=coordinates[0], longitude=coordinates[1], providers_attempted=["DETERMINISTIC_FIXTURE"],
            )
        return GeocodeResponse(
            address=request.address, normalized_address=normalized or None, geocode_status="NOT_FOUND",
            provider="DETERMINISTIC_FIXTURE", candidate_count=0,
            reason="ADDRESS_NOT_IN_DETERMINISTIC_FIXTURE", providers_attempted=["DETERMINISTIC_FIXTURE"],
        )

    latitude, longitude, metadata = MapApiAdapter().geocode_address(request.address)
    return GeocodeResponse(
        address=request.address,
        normalized_address=metadata.get("matched_address") or normalized or None,
        geocode_status=str(metadata.get("geocode_status", "PROVIDER_ERROR")),
        provider=metadata.get("provider"),
        candidate_count=metadata.get("candidate_count"),
        match_type=metadata.get("match_type"),
        latitude=latitude,
        longitude=longitude,
        reason=metadata.get("reason"),
        provider_error_code=metadata.get("provider_error_code"),
        providers_attempted=list(metadata.get("providers_attempted", [])),
        failure_codes=list(metadata.get("failure_codes", [])),
    )


# Legacy singular endpoints remain thin wrappers over the same orchestrator.
@app.post("/v1/analysis", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def submit_analysis(job: AnalysisJobRequest) -> JobAccepted:
    key = _idempotency(job, None)
    _check_submission(job, key)
    job_runner().submit(job.research_request.run_id, lambda: _execute(job, key))
    return JobAccepted(
        run_id=job.research_request.run_id,
        status="QUEUED",
        status_url=f"/v1/research/{job.research_request.run_id}",
        result_url=f"/v1/analyses/{job.research_request.run_id}/result",
    )


@app.post("/v1/analysis/sync")
def run_analysis_sync(job: AnalysisJobRequest) -> dict[str, Any]:
    key = _idempotency(job, None)
    existing = _check_submission(job, key)
    execution = AnalysisExecution(existing, None, None) if existing else analysis_orchestrator().run(
        job.store_profile, job.research_request, job.official_data_requests, key
    )
    result = execution.result
    services().audit.update_run(job.research_request.run_id, "COMPLETED")
    return _serialize_result(result)


def _serialize_result(result: AnalysisResultV1) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "report": {
            "run_id": result.run_id,
            "baseline_scenario": result.scenarios.get("BASELINE").model_dump(mode="json") if result.scenarios.get("BASELINE") else None,
            "relief_options": [item.model_dump(mode="json") for item in result.policies.benefit_simulations],
        },
        "accepted_events": [item.model_dump(mode="json") for item in result.research.accepted_events],
        "rejected_events": [item.model_dump(mode="json") for item in result.research.rejected_events],
        "policies": [item.model_dump(mode="json") for item in result.policies.candidates],
        "signals": [item.model_dump(mode="json") for item in result.signals],
        "adjustments": {key: item.model_dump(mode="json") for key, item in result.adjustments.items()},
        "errors": result.research.errors,
        "analysis_result": result.model_dump(mode="json"),
    }


@app.get("/v1/research/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    row = services().audit.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    result = analysis_orchestrator().result_repository.get(run_id)
    payload = {
        "run_id": run_id,
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if result:
        payload["result"] = _serialize_result(result)
    with _lock:
        if run_id in _errors:
            payload["error"] = _errors[run_id]
    return payload


@app.get("/v1/sources/{source_id}")
def get_source(source_id: str, revision_id: str | None = None) -> dict[str, Any]:
    try:
        return services().sources.get(source_id, revision_id).model_dump(mode="json")
    except Exception as research_error:
        official = analysis_orchestrator().official_pipeline.repository
        vintage = official.get_source_vintage(source_id, revision_id) if official else None
        if vintage is not None:
            return {
                "schema_version": "official_source_vintage.v1",
                **vintage.model_dump(mode="json"),
            }
        raise HTTPException(status_code=404, detail="source not found") from research_error


@app.get("/v1/events")
def list_events(run_id: str, accepted_only: bool = True) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in services().events.list_events(run_id, accepted_only)]


def run() -> None:
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
    )
