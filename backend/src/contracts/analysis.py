"""Top-level, versioned analysis result and traceability contracts."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from src.contracts.attribution import (
    ForecastLayerComparison,
    ResearchFinding,
    ResearchResultSummary,
    SectionStatusSummary,
)
from src.contracts.financial import FinancialScenarioResult
from src.contracts.forecast import BaselineForecastBundle
from src.contracts.official import OfficialDataBundle, OfficialFeatureSet
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import StrictModel
from src.contracts.scenario import ScenarioAdjustmentV2
from src.contracts.summary import GroundedSummary
from src.contracts.store_signal import StoreSignal
from src.relief.benefit_simulator import ReliefBenefitComparison


class AnalysisRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SectionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class AnalysisSection(str, Enum):
    INPUT = "INPUT"
    OFFICIAL_DATA = "OFFICIAL_DATA"
    BASELINE = "BASELINE"
    RESEARCH = "RESEARCH"
    SIGNALS = "SIGNALS"
    FINANCE = "FINANCE"
    POLICIES = "POLICIES"
    RESULT_ASSEMBLY = "RESULT_ASSEMBLY"


class SectionExecution(StrictModel):
    status: SectionStatus = SectionStatus.NOT_STARTED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    record_count: int = Field(default=0, ge=0)
    input_hash: str | None = None
    output_hash: str | None = None


class TraceabilityManifest(StrictModel):
    source_ids: list[str] = Field(default_factory=list)
    source_revision_ids: list[str] = Field(default_factory=list)
    official_snapshot_ids: list[str] = Field(default_factory=list)
    official_observation_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    model_run_ids: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)
    calculation_result_ids: list[str] = Field(default_factory=list)


class VersionManifest(StrictModel):
    input_schema_version: str = "analysis_job_request.v1"
    analysis_result_schema_version: str = "analysis_result.v1"
    official_observation_schema_version: str = "official_observation.v1"
    event_registry_version: str = "event_types.v1"
    normalization_rules_version: str = "normalization_rules.v1"
    source_policy_version: str = "source_tiers.v1"
    coefficient_version: str = "coefficients.v1"
    official_feature_version: str = "official_features.v2.decayed_capped"
    forecast_model_versions: dict[str, str] = Field(default_factory=dict)
    policy_rule_version: str = "policy_rules.v1"
    financial_calculation_version: str = "financial_calculation.v2"
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    provider_models: dict[str, str] = Field(default_factory=dict)
    git_commit: str = "unknown"
    git_dirty: bool = False
    working_tree_diff_hash: str = "unknown"
    untracked_file_manifest_hash: str = "unknown"
    configuration_fingerprint: str = "unknown"
    source_snapshot_schema_version: str = "routing_metadata.v1"


class PolicySearchContext(StrictModel):
    cash_burn_date: str | None = None
    liquidity_risk_date: str | None = None
    required_funding_krw: Decimal = Field(default=Decimal("0"), ge=0)
    business_type_code: str
    region_codes: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=lambda: ["WORKING_CAPITAL"])


class PolicyEligibilityResult(StrictModel):
    policy_id: str
    status: str
    reason: str
    source_ids: list[str] = Field(default_factory=list)


class RankedPolicyOption(StrictModel):
    policy_id: str
    rank: int = Field(ge=1)
    score: Decimal
    reasons: list[str] = Field(default_factory=list)


class PolicyStageCounts(StrictModel):
    extracted_candidates: int = Field(default=0, ge=0)
    reference_only_materials: int = Field(default=0, ge=0)
    validated_policies: int = Field(default=0, ge=0)
    closed_policies: int = Field(default=0, ge=0)
    eligible_policies: int = Field(default=0, ge=0)
    ranked_recommendations: int = Field(default=0, ge=0)


class PolicyResultBundle(StrictModel):
    search_context: PolicySearchContext
    # Deliberately separate policy visibility states for clients.
    candidates: list[PolicyCandidate] = Field(default_factory=list)
    extracted_candidates: list[PolicyCandidate] = Field(default_factory=list)
    eligible_recommendations: list[RankedPolicyOption] = Field(default_factory=list)
    reference_only_materials: list[ResearchFinding] = Field(default_factory=list)
    validation_results: list[dict[str, Any]] = Field(default_factory=list)
    eligibility_results: list[PolicyEligibilityResult] = Field(default_factory=list)
    benefit_simulations: list[ReliefBenefitComparison] = Field(default_factory=list)
    ranked_options: list[RankedPolicyOption] = Field(default_factory=list)
    stage_counts: PolicyStageCounts = Field(default_factory=PolicyStageCounts)
    official_confirmation_required: bool = True
    version: str = "policy_result_bundle.v1"

    @model_validator(mode="after")
    def canonical_policy_ids_are_unique(self) -> "PolicyResultBundle":
        for field_name in ("candidates", "extracted_candidates"):
            identifiers = [
                item.policy_candidate_id for item in getattr(self, field_name)
            ]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(
                    f"duplicate canonical policy IDs remain in {field_name}"
                )
            extractor_ids = [
                item.extractor_policy_candidate_id
                for item in getattr(self, field_name)
                if item.extractor_policy_candidate_id is not None
            ]
            if len(extractor_ids) != len(set(extractor_ids)):
                raise ValueError(
                    f"duplicate policy extractor IDs remain in {field_name}"
                )
        return self


class EvidenceReplayContext(StrictModel):
    mode: str
    fixture_id: str
    captured_from: str
    source_urls: list[str] = Field(default_factory=list)
    notice: str = "재현 가능한 근거 시연이며 현재 시점의 실시간 검색 결과가 아닙니다."


class AnalysisResultV1(StrictModel):
    schema_version: str = "analysis_result.v1"
    result_id: str
    result_version: int = Field(ge=1)
    run_id: str
    tenant_id: str = "default"
    idempotency_key: str
    status: AnalysisRunStatus
    created_at: datetime
    completed_at: datetime | None = None
    as_of_date: date
    forecast_start: date
    forecast_end: date
    deterministic_hash: str
    sections: dict[AnalysisSection, SectionExecution]
    input_snapshot: dict[str, Any]
    official_data: OfficialDataBundle
    official_features: OfficialFeatureSet | None = None
    trend_baseline: BaselineForecastBundle | None = None
    trend_scenario: FinancialScenarioResult | None = None
    baseline: BaselineForecastBundle
    research: ResearchResultSummary
    signals: list[StoreSignal] = Field(default_factory=list)
    adjustments: dict[str, ScenarioAdjustmentV2] = Field(default_factory=dict)
    scenarios: dict[str, FinancialScenarioResult] = Field(default_factory=dict)
    forecast_layer_comparisons: list[ForecastLayerComparison] = Field(default_factory=list)
    section_status_summary: list[SectionStatusSummary] = Field(default_factory=list)
    policies: PolicyResultBundle
    grounded_summary: GroundedSummary | None = None
    traceability: TraceabilityManifest
    versions: VersionManifest
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_replay: EvidenceReplayContext | None = None


def canonical_json_hash(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def analysis_payload_hash(result: AnalysisResultV1 | dict[str, Any]) -> str:
    payload = result.model_dump(mode="json") if isinstance(result, AnalysisResultV1) else dict(result)
    for key in ("deterministic_hash", "created_at", "completed_at", "result_id", "result_version"):
        payload.pop(key, None)
    sections = payload.get("sections", {})
    for section in sections.values():
        section.pop("started_at", None)
        section.pop("completed_at", None)
    for section in payload.get("section_status_summary", []):
        section.pop("started_at", None)
        section.pop("completed_at", None)
    research = payload.get("research", {})
    for agent in research.get("agent_summaries", []):
        # Runtime observability is persisted but cannot affect replay identity.
        agent.pop("elapsed_time_ms_by_stage", None)
    for bundle in research.get("bundles", []):
        diagnostics = bundle.get("diagnostics", {})
        diagnostics.pop("elapsed_time_ms_by_stage", None)
        metadata = bundle.get("metadata", {})
        metadata.pop("stage_elapsed_ms", None)


    return canonical_json_hash(payload)
