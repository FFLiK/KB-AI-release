"""Typed UI attribution, research, and forecast-layer contracts."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from typing import Literal

from pydantic import Field, model_validator

from src.contracts.canonical_event import CanonicalEvent
from src.contracts.event_candidate import EventImpact, EvidenceRef, LocationRaw, TemporalRaw
from src.contracts.research import AgentType, ResearchBundle, StrictModel


class ValidationFailureDetail(StrictModel):
    code: str
    message: str
    retryable: bool = False


class RetryMetadata(StrictModel):
    attempted: bool = False
    outcome: str | None = None
    candidate_id: str | None = None


class RejectedEventCandidateSummary(StrictModel):
    candidate_id: str
    status: str
    failure_codes: list[str] = Field(default_factory=list)
    failure_details: list[ValidationFailureDetail] = Field(default_factory=list)
    domain: str | None = None
    event_family: str | None = None
    event_type: str | None = None
    title: str | None = None
    actor_org_raw: str | None = None
    target_subject_raw: str | None = None
    temporal: TemporalRaw = Field(default_factory=TemporalRaw)
    location: LocationRaw = Field(default_factory=LocationRaw)
    affected_industries_raw: list[str] = Field(default_factory=list)
    impacts: list[EventImpact] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    source_revision_ids: list[str] = Field(default_factory=list)
    signal_enabled: bool = False
    event_type_signal_enabled: bool = False
    candidate_signal_eligible: bool = False
    signal_eligibility_reason: str = "Signal eligibility metadata was not available."
    retry: RetryMetadata = Field(default_factory=RetryMetadata)
    validation_metadata: dict[str, Any] = Field(default_factory=dict)
    lifecycle_stages: list[str] = Field(default_factory=lambda: ["DISCOVERED", "EXTRACTED"])
    primary_exclusion_reason: str | None = None
    expected_impact_if_unblocked: str | None = None


class EventPipelineOutcome(StrictModel):
    event_id: str | None = None
    candidate_id: str | None = None
    title: str
    lifecycle_stages: list[str] = Field(default_factory=list)
    terminal_status: str
    primary_exclusion_reason: str | None = None
    signal_eligible: bool = False
    event_type_signal_enabled: bool = False
    candidate_signal_eligible: bool = False
    store_distance_meters: float | None = Field(default=None, ge=0)
    configured_radius_meters: float | None = Field(default=None, ge=0)
    financial_exposure_relevance: str
    expected_impact_if_unblocked: str
    signal_ids: list[str] = Field(default_factory=list)


class ResearchFunnel(StrictModel):
    query_count: int = Field(default=0, ge=0)
    discovery_hit_count: int = Field(default=0, ge=0)
    document_count: int = Field(default=0, ge=0)
    fetched_document_count: int = Field(default=0, ge=0)
    resolved_source_count: int = Field(default=0, ge=0)
    usable_document_count: int = Field(default=0, ge=0)
    access_failure_count: int = Field(default=0, ge=0)
    navigation_only_count: int = Field(default=0, ge=0)
    duplicate_document_count: int = Field(default=0, ge=0)
    reference_finding_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    rejected_candidate_count: int = Field(default=0, ge=0)
    accepted_event_count: int = Field(default=0, ge=0)
    signal_eligible_event_count: int = Field(default=0, ge=0)
    applied_signal_count: int = Field(default=0, ge=0)
    provider_failure_count: int = Field(default=0, ge=0)
    operation_timeout_count: int = Field(default=0, ge=0)
    timeout_agent_count: int = Field(default=0, ge=0)
    usable_document_ratio: float = Field(default=0, ge=0, le=1)
    navigation_only_ratio: float = Field(default=0, ge=0, le=1)
    extraction_tokens_per_usable_candidate: float | None = Field(default=None, ge=0)


class AgentResearchSummary(StrictModel):
    agent_type: str
    category: str
    status: str
    query_count: int = Field(default=0, ge=0)
    discovered_hit_count: int = Field(default=0, ge=0)
    fetched_document_count: int = Field(default=0, ge=0)
    document_count: int = Field(default=0, ge=0)
    usable_document_count: int = Field(default=0, ge=0)
    finding_count: int = Field(default=0, ge=0)
    provider_failure_count: int = Field(default=0, ge=0)
    deduplicated_document_count: int = Field(default=0, ge=0)
    extraction_tokens_per_usable_candidate: float | None = Field(default=None, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    access_failure_count: int = Field(default=0, ge=0)
    model_call_count: int = Field(default=0, ge=0)
    no_result_reasons: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    timeout_stage: str | None = None
    operation_timeout_counts: dict[str, int] = Field(default_factory=dict)
    partial_output_counts: dict[str, int] = Field(default_factory=dict)
    configured_limits: dict[str, int | float | None] = Field(default_factory=dict)
    elapsed_time_ms_by_stage: dict[str, int] = Field(default_factory=dict)
    skipped_counts: dict[str, int] = Field(default_factory=dict)
    models: list[str] = Field(default_factory=list)
    total_latency_ms: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class NoSignalExplanation(StrictModel):
    headline: str
    reason_codes: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    limitation: str


class ResearchFinding(StrictModel):
    finding_id: str
    research_run_id: str
    agent_type: AgentType
    domain: str
    title: str
    relevance_summary: str
    temporal_raw: str | None = None
    location_raw: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    source_revision_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    status: str = "REFERENCE_ONLY"
    reason_code: str
    recommended_follow_up: str = "REVIEW_SOURCE"
    financial_signal_eligible: Literal[False] = False
    rate_selection_method: str | None = None
    rate_evidence_id: str | None = None
    reference_freshness_status: str | None = None
    reference_temporal_reason_codes: list[str] = Field(default_factory=list)


class ResearchResultSummary(StrictModel):
    version: str = "research_result_summary.v1"
    bundles: list[ResearchBundle] = Field(default_factory=list)
    accepted_events: list[CanonicalEvent] = Field(default_factory=list)
    rejected_events: list[RejectedEventCandidateSummary] = Field(default_factory=list)
    reference_findings: list[ResearchFinding] = Field(default_factory=list)
    event_pipeline_outcomes: list[EventPipelineOutcome] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    risk_status: str = "COMPLETED"
    policy_status: str = "COMPLETED"
    funnel: ResearchFunnel = Field(default_factory=ResearchFunnel)
    agent_summaries: list[AgentResearchSummary] = Field(default_factory=list)
    no_signal_explanation: NoSignalExplanation | None = None

    @model_validator(mode="after")
    def event_lifecycle_is_consistent(self) -> "ResearchResultSummary":
        accepted_ids = [
            candidate_id for event in self.accepted_events
            for candidate_id in event.candidate_ids
        ]
        rejected_ids = [item.candidate_id for item in self.rejected_events]
        outcome_ids = [
            item.candidate_id for item in self.event_pipeline_outcomes
            if item.candidate_id is not None
        ]
        if len(accepted_ids) != len(set(accepted_ids)):
            raise ValueError("duplicate accepted event candidate IDs")
        if len(rejected_ids) != len(set(rejected_ids)):
            raise ValueError("duplicate rejected event candidate IDs")
        if set(accepted_ids).intersection(rejected_ids):
            raise ValueError("candidate ID has both accepted and rejected outcomes")
        expected_ids = set(accepted_ids) | set(rejected_ids)
        if len(outcome_ids) != len(set(outcome_ids)) or set(outcome_ids) != expected_ids:
            raise ValueError("event pipeline outcomes must resolve every candidate exactly once")
        if self.funnel.candidate_count != len(expected_ids):
            raise ValueError("funnel candidate count does not match serialized candidates")
        if self.funnel.rejected_candidate_count != len(rejected_ids):
            raise ValueError("funnel rejected count does not match serialized candidates")
        if self.funnel.accepted_event_count != len(accepted_ids):
            raise ValueError("funnel accepted count does not match serialized candidates")
        return self

class MonthlyScenarioDelta(StrictModel):
    month: str
    base_revenue_cash_krw: Decimal
    comparison_revenue_cash_krw: Decimal
    revenue_cash_delta_krw: Decimal
    base_ingredient_cost_krw: Decimal
    comparison_ingredient_cost_krw: Decimal
    ingredient_cost_delta_krw: Decimal
    ingredient_cost_savings_krw: Decimal
    base_interest_payment_krw: Decimal
    comparison_interest_payment_krw: Decimal
    interest_payment_delta_krw: Decimal
    base_net_cash_flow_krw: Decimal
    comparison_net_cash_flow_krw: Decimal
    net_cash_flow_delta_krw: Decimal
    base_ending_cash_krw: Decimal
    comparison_ending_cash_krw: Decimal
    ending_cash_delta_krw: Decimal


class FinancialAttributionComponent(StrictModel):
    component: str
    label: str
    signed_cash_effect_krw: Decimal


class ForecastLayerComparison(StrictModel):
    comparison_id: str
    base_layer: str
    comparison_layer: str
    attribution_scope: str = "FEATURE_GROUP"
    monthly_deltas: list[MonthlyScenarioDelta] = Field(default_factory=list)
    ending_cash_delta_krw: Decimal = Decimal("0")
    attribution: list[FinancialAttributionComponent] = Field(default_factory=list)
    source_feature_set_id: str | None = None
    event_ids: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    base_scenario_id: str | None = None
    comparison_scenario_id: str | None = None


class SectionStatusSummary(StrictModel):
    section: str
    label: str
    status: str
    record_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    failure_codes: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    effect: str


class CandidateEvidenceSource(StrictModel):
    source_id: str
    source_revision_id: str
    title: str = ""
    publisher: str | None = None
    canonical_url: str
    retrieved_at: datetime
    access_status: str
    http_status: int | None = None
    content_type: str | None = None


class CandidateEvidenceResponse(StrictModel):
    candidate_id: str
    validation_status: str
    failure_codes: list[str] = Field(default_factory=list)
    failure_details: list[ValidationFailureDetail] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    sources: list[CandidateEvidenceSource] = Field(default_factory=list)
    retry: RetryMetadata = Field(default_factory=RetryMetadata)
    validation_metadata: dict[str, Any] = Field(default_factory=dict)
    lifecycle_stages: list[str] = Field(default_factory=lambda: ["DISCOVERED", "EXTRACTED"])
    primary_exclusion_reason: str | None = None
    expected_impact_if_unblocked: str | None = None
