from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field, model_validator

from src.contracts.event_candidate import Domain, EventImpact, EventType, EvidenceRef
from src.contracts.research import StrictModel


class NormalizationRecord(StrictModel):
    field_path: str
    raw_value: str | None
    normalized_value: str | float | int | None
    rule_id: str
    rule_version: str = "v1"
    source_id: str | None = None
    source_revision_id: str | None = None
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    anchor_source: str | None = None


class CanonicalLocation(StrictModel):
    text_raw: str | None = None
    normalized_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geometry_geojson: dict[str, Any] | None = None
    geocode_status: str = "NOT_REQUIRED"
    geocode_provider: str | None = None
    match_method: str | None = None
    distance_meters: float | None = Field(default=None, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    resolution_metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalEvent(StrictModel):
    event_id: str
    candidate_ids: list[str] = Field(min_length=1)
    research_run_id: str
    domain: Domain
    event_family: str
    event_type: EventType
    title: str
    actor_org_id: str | None = None
    actor_org_raw: str | None = None
    target_subject_id: str | None = None
    target_subject_raw: str | None = None
    start_date: date
    end_date: date | None = None
    location: CanonicalLocation
    affected_industry_codes: list[str] = Field(default_factory=list)
    impacts: list[EventImpact] = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    source_revision_ids: list[str] = Field(min_length=1)
    source_tier: str
    validation_status: str
    validation_failure_codes: list[str] = Field(default_factory=list)
    normalization_records: list[NormalizationRecord] = Field(min_length=1)
    fingerprint: str
    cause_group_id: str | None = None
    signal_enabled: bool = True
    signal_eligibility_reason: str = "Event type is eligible to generate a financial signal."
    schema_version: str = "canonical_event.v1"
    registry_version: str = "event_types.v1"

    @model_validator(mode="after")
    def accepted_invariants(self) -> "CanonicalEvent":
        if self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if self.validation_status == "ACCEPTED":
            if not self.evidence or not self.source_revision_ids:
                raise ValueError("ACCEPTED events require evidence and source revisions")
            if self.validation_failure_codes:
                raise ValueError("ACCEPTED events cannot contain validation failures")
        return self
