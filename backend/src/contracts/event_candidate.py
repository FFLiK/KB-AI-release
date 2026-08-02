from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from src.contracts.research import StrictModel


class Domain(str, Enum):
    MACRO = "MACRO"
    INDUSTRY = "INDUSTRY"
    LOCAL = "LOCAL"
    POLICY = "POLICY"


class ImpactAxis(str, Enum):
    REVENUE_DEMAND = "REVENUE_DEMAND"
    INGREDIENT_COST = "INGREDIENT_COST"
    INTEREST_COST = "INTEREST_COST"
    PLATFORM_COST = "PLATFORM_COST"
    OPERATING_COST = "OPERATING_COST"
    COMPETITION = "COMPETITION"
    UNCERTAINTY = "UNCERTAINTY"


class ImpactDirection(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    HOLD = "HOLD"
    UNKNOWN = "UNKNOWN"


class EventType(str, Enum):
    BASE_RATE_INCREASE = "BASE_RATE_INCREASE"
    BASE_RATE_DECREASE = "BASE_RATE_DECREASE"
    BASE_RATE_HOLD = "BASE_RATE_HOLD"
    KRW_DEPRECIATION = "KRW_DEPRECIATION"
    KRW_APPRECIATION = "KRW_APPRECIATION"
    FX_VOLATILITY_ALERT = "FX_VOLATILITY_ALERT"
    IMPORT_INPUT_PRICE_INCREASE = "IMPORT_INPUT_PRICE_INCREASE"
    IMPORT_INPUT_PRICE_DECREASE = "IMPORT_INPUT_PRICE_DECREASE"
    INPUT_SUPPLY_DISRUPTION = "INPUT_SUPPLY_DISRUPTION"
    INPUT_SUPPLY_RECOVERY = "INPUT_SUPPLY_RECOVERY"
    OFFICIAL_OUTLOOK_UPGRADE = "OFFICIAL_OUTLOOK_UPGRADE"
    OFFICIAL_OUTLOOK_DOWNGRADE = "OFFICIAL_OUTLOOK_DOWNGRADE"
    FNB_DEMAND_INCREASE = "FNB_DEMAND_INCREASE"
    FNB_DEMAND_DECREASE = "FNB_DEMAND_DECREASE"
    INGREDIENT_SHORTAGE = "INGREDIENT_SHORTAGE"
    INGREDIENT_SUPPLY_RECOVERY = "INGREDIENT_SUPPLY_RECOVERY"
    WHOLESALE_PRICE_INCREASE = "WHOLESALE_PRICE_INCREASE"
    WHOLESALE_PRICE_DECREASE = "WHOLESALE_PRICE_DECREASE"
    PLATFORM_FEE_INCREASE = "PLATFORM_FEE_INCREASE"
    PLATFORM_FEE_DECREASE = "PLATFORM_FEE_DECREASE"
    PLATFORM_TERMS_TIGHTEN = "PLATFORM_TERMS_TIGHTEN"
    PLATFORM_TERMS_EASE = "PLATFORM_TERMS_EASE"
    PLATFORM_SERVICE_OUTAGE = "PLATFORM_SERVICE_OUTAGE"
    REGULATION_TIGHTEN = "REGULATION_TIGHTEN"
    REGULATION_EASE = "REGULATION_EASE"
    PRODUCT_RECALL = "PRODUCT_RECALL"
    SALES_RESTRICTION = "SALES_RESTRICTION"
    PEDESTRIAN_FULL_CLOSURE = "PEDESTRIAN_FULL_CLOSURE"
    PEDESTRIAN_PARTIAL_CLOSURE = "PEDESTRIAN_PARTIAL_CLOSURE"
    VEHICLE_ONLY_RESTRICTION = "VEHICLE_ONLY_RESTRICTION"
    ROAD_FULL_CLOSURE = "ROAD_FULL_CLOSURE"
    ROAD_PARTIAL_CLOSURE = "ROAD_PARTIAL_CLOSURE"
    PARKING_RESTRICTION = "PARKING_RESTRICTION"
    TRANSIT_SERVICE_DISRUPTION = "TRANSIT_SERVICE_DISRUPTION"
    TRANSIT_SERVICE_IMPROVEMENT = "TRANSIT_SERVICE_IMPROVEMENT"
    NEW_STATION_OPENING = "NEW_STATION_OPENING"
    LOCAL_FESTIVAL = "LOCAL_FESTIVAL"
    LARGE_GATHERING_EVENT = "LARGE_GATHERING_EVENT"
    EVENT_CANCELLED = "EVENT_CANCELLED"
    CONSTRUCTION_START = "CONSTRUCTION_START"
    CONSTRUCTION_SCOPE_EXPANSION = "CONSTRUCTION_SCOPE_EXPANSION"
    CONSTRUCTION_END = "CONSTRUCTION_END"
    MAJOR_FACILITY_OPENING = "MAJOR_FACILITY_OPENING"
    MAJOR_FACILITY_CLOSURE = "MAJOR_FACILITY_CLOSURE"
    COMPETITOR_OPENING = "COMPETITOR_OPENING"
    COMPETITOR_CLOSURE = "COMPETITOR_CLOSURE"
    DISASTER_WARNING = "DISASTER_WARNING"
    EVACUATION_ORDER = "EVACUATION_ORDER"
    ACCESS_RESTRICTION = "ACCESS_RESTRICTION"
    RECOVERY_DECLARED = "RECOVERY_DECLARED"
    MINIMUM_WAGE_INCREASE = "MINIMUM_WAGE_INCREASE"
    TAX_OR_FEE_INCREASE = "TAX_OR_FEE_INCREASE"
    TAX_OR_FEE_DECREASE = "TAX_OR_FEE_DECREASE"
    OPERATING_RESTRICTION = "OPERATING_RESTRICTION"
    OPERATING_RESTRICTION_EASE = "OPERATING_RESTRICTION_EASE"


class TemporalRaw(StrictModel):
    start_raw: str | None = None
    end_raw: str | None = None
    recurrence_raw: str | None = None
    operating_hours_raw: str | None = None


class LocationRaw(StrictModel):
    address_raw: str | None = None
    area_raw: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class EvidenceRef(StrictModel):
    evidence_id: str
    source_id: str
    source_revision_id: str
    field_paths: list[str] = Field(min_length=1)
    quote: str = Field(min_length=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> "EvidenceRef":
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class EventImpact(StrictModel):
    axis: ImpactAxis
    direction: ImpactDirection
    mechanism: str
    evidence_ids: list[str] = Field(min_length=1)


class ExtractionMetadata(StrictModel):
    schema_version: str = "event_candidate.v1"
    registry_version: str = "event_types.v1"
    model: str
    prompt_version: str
    reasoning_level: str = "LOW"


class ExtractedEventCandidate(StrictModel):
    candidate_id: str
    research_run_id: str
    domain: Domain
    event_family: str
    event_type: EventType
    title: str = Field(min_length=1)
    actor_org_raw: str | None = None
    target_subject_raw: str | None = None
    temporal: TemporalRaw
    location: LocationRaw
    affected_industries_raw: list[str] = Field(default_factory=list)
    impacts: list[EventImpact] = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(min_length=1)
    extraction_metadata: ExtractionMetadata

    @model_validator(mode="after")
    def every_impact_references_evidence(self) -> "ExtractedEventCandidate":
        ids = {item.evidence_id for item in self.evidence}
        for impact in self.impacts:
            missing = set(impact.evidence_ids) - ids
            if missing:
                raise ValueError(f"impact references missing evidence ids: {sorted(missing)}")
        return self
