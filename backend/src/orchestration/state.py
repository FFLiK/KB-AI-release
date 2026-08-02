"""Shared orchestration state used by legacy compatibility wrappers."""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class AppState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    as_of_date: str
    input_profile: Optional[dict[str, Any]] = None
    input_validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    official_indicators: list[dict[str, Any]] = Field(default_factory=list)
    official_data_bundle: Optional[dict[str, Any]] = None
    official_data_vintages: list[dict[str, Any]] = Field(default_factory=list)
    baseline_model_results: dict[str, Any] = Field(default_factory=dict)
    model_metrics: list[dict[str, Any]] = Field(default_factory=list)
    extracted_events: list[dict[str, Any]] = Field(default_factory=list)
    accepted_events: list[dict[str, Any]] = Field(default_factory=list)
    rejected_events: list[dict[str, Any]] = Field(default_factory=list)
    cause_groups: list[dict[str, Any]] = Field(default_factory=list)
    signal_scores: dict[str, Any] = Field(default_factory=dict)
    scenario_adjustments: dict[str, Any] = Field(default_factory=dict)
    financial_results: dict[str, Any] = Field(default_factory=dict)
    policy_candidates: list[dict[str, Any]] = Field(default_factory=list)
    policy_validation_logs: list[dict[str, Any]] = Field(default_factory=list)
    eligibility_results: list[dict[str, Any]] = Field(default_factory=list)
    benefit_simulations: list[dict[str, Any]] = Field(default_factory=list)
    section_statuses: dict[str, Any] = Field(default_factory=dict)
    version_manifest: dict[str, Any] = Field(default_factory=dict)
    deterministic_result_hash: Optional[str] = None
    result_id: Optional[str] = None
    result_version: Optional[int] = None
    deterministic_report: Optional[dict[str, Any]] = None
