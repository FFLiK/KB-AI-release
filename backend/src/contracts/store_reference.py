"""Contracts for public business/entity and location reference data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from src.contracts.research import StrictModel


class BusinessLocationRecord(StrictModel):
    business_id: str = Field(min_length=1)
    business_name: str = Field(min_length=1)
    branch_name: str | None = None
    industry_large_code: str | None = None
    industry_large_name: str | None = None
    industry_middle_code: str | None = None
    industry_middle_name: str | None = None
    industry_small_code: str | None = None
    industry_small_name: str | None = None
    standard_industry_code: str | None = None
    standard_industry_name: str | None = None
    lot_address: str | None = None
    road_address: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    province_code: str | None = None
    province_name: str | None = None
    district_code: str | None = None
    district_name: str | None = None
    administrative_dong_code: str | None = None
    administrative_dong_name: str | None = None
    legal_dong_code: str | None = None
    legal_dong_name: str | None = None
    postal_code: str | None = None
    provider_reference_month: str = Field(pattern=r"^\d{6}$")
    source_id: str
    source_revision_id: str

    @model_validator(mode="after")
    def require_address(self) -> "BusinessLocationRecord":
        if not (self.road_address or self.lot_address):
            raise ValueError("at least one provider address is required")
        return self


class StoreReferenceSnapshot(StrictModel):
    snapshot_id: str
    provider: str = "PUBLIC_DATA_SDSC"
    endpoint: str
    provider_reference_month: str = Field(pattern=r"^\d{6}$")
    retrieved_at: datetime
    source_id: str
    source_revision_id: str
    body_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    records: list[BusinessLocationRecord] = Field(default_factory=list)
    raw_payload: list[dict[str, Any]] = Field(default_factory=list)
    version: str = "store_reference_snapshot.v1"

    @model_validator(mode="after")
    def require_aware_retrieval_time(self) -> "StoreReferenceSnapshot":
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return self
