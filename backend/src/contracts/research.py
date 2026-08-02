"""Strict public contracts for research runs."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class AgentType(str, Enum):
    MACRO = "MACRO"
    INDUSTRY = "INDUSTRY"
    LOCAL_EVENT = "LOCAL_EVENT"
    POLICY_REGULATION = "POLICY_REGULATION"


class ReasoningLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ResearchRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DocumentResearchStatus(str, Enum):
    CANDIDATES_EXTRACTED = "CANDIDATES_EXTRACTED"
    REFERENCE_FINDINGS_ONLY = "REFERENCE_FINDINGS_ONLY"
    NO_DISCRETE_EVENT = "NO_DISCRETE_EVENT"
    INSUFFICIENT_TEMPORAL_EVIDENCE = "INSUFFICIENT_TEMPORAL_EVIDENCE"
    INSUFFICIENT_IMPACT_EVIDENCE = "INSUFFICIENT_IMPACT_EVIDENCE"
    OUTSIDE_FORECAST_CONTEXT = "OUTSIDE_FORECAST_CONTEXT"
    SOURCE_CONTENT_UNUSABLE = "SOURCE_CONTENT_UNUSABLE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    DUPLICATE_SOURCE = "DUPLICATE_SOURCE"
    STRUCTURED_LIST_TRAVERSED = "STRUCTURED_LIST_TRAVERSED"


class ProviderFailureDetail(StrictModel):
    stage: str
    provider: str
    model: str | None = None
    document_id: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_type: str
    error_code: str | None = None
    parameter: str | None = None
    request_id: str | None = None
    retryable: bool = False
    retry_attempted: bool = False


class DocumentResearchOutcome(StrictModel):
    source_id: str
    source_revision_id: str | None = None
    agent_type: AgentType
    status: DocumentResearchStatus
    reason_codes: list[str] = Field(default_factory=list)
    final_url_resolved: bool = False
    usable_for_extraction: bool = False
    extraction_attempted: bool = False
    candidate_count: int = Field(default=0, ge=0)
    finding_count: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    body_characters: int = Field(default=0, ge=0)
    truncated: bool = False
    page_type: str | None = None
    classification_reasons: list[str] = Field(default_factory=list)
    snapshot_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    routing_metadata_version: str | None = None


class StoreLocation(StrictModel):
    address: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    administrative_area: str | None = None
    commercial_area: str | None = None


class ResearchRequest(StrictModel):
    run_id: str = Field(min_length=1, max_length=48)
    as_of_date: date
    tenant_id: str = Field(default="default", min_length=1, max_length=64)
    forecast_start: date
    forecast_end: date
    store_profile_snapshot_id: str
    business_type_code: str
    ingredient_categories: list[str] = Field(default_factory=list)
    platform_usage: list[str] = Field(default_factory=list)
    store_location: StoreLocation
    administrative_area_codes: list[str] = Field(default_factory=list)
    search_radius_m: int = Field(default=1500, ge=50, le=100_000)
    official_indicator_snapshot_ids: list[str] = Field(default_factory=list)
    event_registry_version: str = "event_types.v1"
    source_policy_version: str = "source_tiers.v1"
    policy_search_terms: list[str] = Field(default_factory=list)
    required_funding_krw: Decimal | None = Field(default=None, ge=0)
    projected_cash_burn_date: date | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "ResearchRequest":
        if self.forecast_start > self.forecast_end:
            raise ValueError("forecast_start must not be after forecast_end")
        if self.as_of_date > self.forecast_end:
            raise ValueError("as_of_date must not be after forecast_end")
        return self


class SearchQueryRecord(StrictModel):
    query_id: str
    query: str
    provider: str
    model: str
    reasoning_level: ReasoningLevel
    created_at: datetime
    status: str = "COMPLETED"
    failure_code: str | None = None
    retry_count: int = Field(default=0, ge=0)
    provider_response_id: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    result_order: list[str] = Field(default_factory=list)


class AccessFailure(StrictModel):
    url: str
    code: str
    detail: str
    retryable: bool = False


class ModelCallRecord(StrictModel):
    call_id: str
    provider: str
    model: str
    reasoning_level: ReasoningLevel
    request_id: str | None = None
    prompt_version: str
    schema_version: str
    registry_version: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    search_query_count: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    cost_status: str = "RATE_NOT_CONFIGURED"
    retry_count: int = Field(default=0, ge=0)
    validation_result: str
    created_at: datetime

    @model_validator(mode="after")
    def calculate_cost(self) -> "ModelCallRecord":
        if self.estimated_cost is None:
            from src.extraction.cost_tracking import CostTracker

            self.estimated_cost, self.cost_status = CostTracker().estimate_with_status(
                self.model, self.input_tokens, self.output_tokens, self.cached_tokens
            )
        elif self.cost_status == "RATE_NOT_CONFIGURED":
            self.cost_status = "PROVIDED"
        return self

class ResearchExecutionDiagnostics(StrictModel):
    discovered_hit_count: int = Field(default=0, ge=0)
    fetched_document_count: int = Field(default=0, ge=0)
    usable_document_count: int = Field(default=0, ge=0)
    timeout_stage: str | None = None
    operation_timeout_counts: dict[str, int] = Field(default_factory=dict)
    partial_output_counts: dict[str, int] = Field(default_factory=dict)
    configured_limits: dict[str, int | float | None] = Field(default_factory=dict)
    elapsed_time_ms_by_stage: dict[str, int] = Field(default_factory=dict)
    skipped_counts: dict[str, int] = Field(default_factory=dict)
    cancellation_requested: bool = False


class ResearchBundle(StrictModel):
    research_run_id: str
    agent_type: AgentType
    status: ResearchRunStatus
    search_queries: list[SearchQueryRecord] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    event_candidate_ids: list[str] = Field(default_factory=list)
    policy_candidate_ids: list[str] = Field(default_factory=list)
    access_failures: list[AccessFailure] = Field(default_factory=list)
    no_result_reasons: list[str] = Field(default_factory=list)
    model_call_records: list[ModelCallRecord] = Field(default_factory=list)
    document_outcomes: list[DocumentResearchOutcome] = Field(default_factory=list)
    provider_failures: list[ProviderFailureDetail] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    diagnostics: ResearchExecutionDiagnostics = Field(default_factory=ResearchExecutionDiagnostics)
