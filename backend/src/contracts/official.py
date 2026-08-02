"""Versioned contracts for official numeric observations and snapshots."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from src.contracts.research import StrictModel


class ObservationFrequency(str, Enum):
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class ObservationQualityStatus(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    REVISED = "REVISED"
    REJECTED = "REJECTED"


class OfficialDataStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class OfficialCollectionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    MISSING = "MISSING"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class OfficialDataRequest(StrictModel):
    provider: str
    indicator_id: str
    request_params: dict[str, str | int | float] = Field(default_factory=dict)
    required: bool = False
    max_age_days: int | None = Field(default=None, ge=0)
    target_frequency: ObservationFrequency = ObservationFrequency.MONTHLY
    transform: str = "LAST"


class CanonicalObservation(StrictModel):
    observation_id: str
    indicator_id: str
    value: Decimal
    unit: str
    frequency: ObservationFrequency
    observed_at: date
    released_at: datetime
    available_at: datetime
    source_id: str
    source_revision_id: str
    vintage_id: str
    normalization_rule_id: str = "indicator.v1"
    availability_policy_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    quality_status: ObservationQualityStatus = ObservationQualityStatus.VALID

    @model_validator(mode="after")
    def validate_availability(self) -> "CanonicalObservation":
        if self.available_at < self.released_at:
            raise ValueError("available_at must not be before released_at")
        if self.released_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("released_at and available_at must be timezone-aware")
        return self


class SourceVintage(StrictModel):
    vintage_id: str
    provider: str
    source_id: str
    source_revision_id: str
    revision_basis: str = "PROVIDER"
    retrieved_at: datetime
    body_hash: str
    observation_count: int = Field(ge=0)
    raw_payload: list[dict[str, Any]] = Field(default_factory=list)


class FrequencyTransform(StrictModel):
    indicator_id: str
    from_frequency: ObservationFrequency
    to_frequency: ObservationFrequency
    method: str
    input_observation_ids: list[str] = Field(default_factory=list)
    output_observation_ids: list[str] = Field(default_factory=list)


class FreshnessRecord(StrictModel):
    indicator_id: str
    latest_observed_at: date | None = None
    age_days: int | None = Field(default=None, ge=0)
    max_age_days: int | None = Field(default=None, ge=0)
    is_stale: bool = False


class OfficialIndicatorMetadata(StrictModel):
    indicator_id: str
    display_name: str
    provider: str
    provider_series_code: str | None = None
    feature_role: str
    unit: str | None = None
    frequency: str | None = None
    max_age_days: int | None = Field(default=None, ge=0)
    transformation_method: str = "DECAYED_CAPPED_RECENT_CHANGE_V2"
    affected_model_dimension: str
    description: str | None = None


class OfficialIndicatorCollectionResult(StrictModel):
    provider: str
    indicator_id: str
    requested: bool = True
    required: bool = False
    status: OfficialCollectionStatus
    observation_count: int = Field(default=0, ge=0)
    latest_observation_id: str | None = None
    previous_observation_id: str | None = None
    latest_value: Decimal | None = None
    previous_value: Decimal | None = None
    unit: str | None = None
    absolute_change: Decimal | None = None
    percentage_change: Decimal | None = None
    latest_observed_at: date | None = None
    latest_released_at: datetime | None = None
    latest_available_at: datetime | None = None
    freshness_age_days: int | None = Field(default=None, ge=0)
    freshness_max_age_days: int | None = Field(default=None, ge=0)
    freshness_status: str = "MISSING"
    failure_code: str | None = None
    failure_detail: str | None = None
    missing_data_behavior: str | None = None
    metadata: OfficialIndicatorMetadata


class OfficialEventOverride(StrictModel):
    event_id: str
    indicator_id: str
    effective_date: date
    # An exclusion decision can be auditable even when the source did not
    # explicitly evidence a numeric value or unit. Do not fabricate a zero
    # value merely to satisfy this record contract.
    event_value: Decimal | None = None
    unit: str | None = None
    latest_official_observed_at: date | None = None
    latest_official_value: Decimal | None = None
    status: str
    reason_code: str
    synthetic_observation_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    source_revision_ids: list[str] = Field(default_factory=list)


class OfficialDataBundle(StrictModel):
    snapshot_id: str
    as_of_date: date
    observations: list[CanonicalObservation] = Field(default_factory=list)
    source_vintages: list[SourceVintage] = Field(default_factory=list)
    frequency_transforms: list[FrequencyTransform] = Field(default_factory=list)
    freshness: list[FreshnessRecord] = Field(default_factory=list)
    collection_results: list[OfficialIndicatorCollectionResult] = Field(default_factory=list)
    missing_indicators: list[str] = Field(default_factory=list)
    provider_errors: dict[str, str] = Field(default_factory=dict)
    status: OfficialDataStatus
    version: str = "official_data_bundle.v1"


class IndicatorFeatureContribution(StrictModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    indicator_id: str
    provider: str
    feature_role: str
    affected_model_dimension: str
    latest_observation_id: str
    previous_observation_id: str | None = None
    latest_value: Decimal
    previous_value: Decimal | None = None
    unit: str
    latest_observed_at: date
    latest_released_at: datetime
    absolute_change: Decimal
    relative_change: Decimal
    capped_relative_change: Decimal
    decay_factor: Decimal = Field(default=Decimal("0.65"), gt=0, le=1)
    cumulative_relative_change: Decimal = Decimal("0")
    cumulative_horizon_cap: Decimal = Field(default=Decimal("0.12"), gt=0)
    projection_step: int = Field(ge=1)
    projected_value: Decimal
    contributed_multiplier_delta: Decimal
    transformation_method: str = "DECAYED_CAPPED_RECENT_CHANGE_V2"
    assumptions: list[str] = Field(default_factory=list)
    source_observation_ids: list[str] = Field(default_factory=list)


class MonthlyOfficialFeatures(StrictModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    revenue_index_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    ingredient_cost_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    domestic_ingredient_cost_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    imported_ingredient_cost_multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    interest_rate_delta: Decimal = Decimal("0")
    indicator_values: dict[str, Decimal] = Field(default_factory=dict)
    contributions: list[IndicatorFeatureContribution] = Field(default_factory=list)
    source_observation_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class OfficialFeatureSet(StrictModel):
    feature_set_id: str
    as_of_date: date
    months: list[MonthlyOfficialFeatures] = Field(default_factory=list)
    indicator_ids: list[str] = Field(default_factory=list)
    source_snapshot_id: str | None = None
    status: str = "COMPLETED"
    transformation_version: str = "official_features.v1"
    event_overrides: list[OfficialEventOverride] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    def for_month(self, month: str) -> MonthlyOfficialFeatures:
        for item in self.months:
            if item.month == month:
                return item
        return MonthlyOfficialFeatures(month=month, assumptions=["No official feature was available for month"])
