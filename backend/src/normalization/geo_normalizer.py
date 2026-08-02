from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.ingestion.official_api.map_api import MapApiAdapter


@dataclass(frozen=True)
class GeoCandidate:
    address: str
    latitude: float
    longitude: float
    provider: str | None = None
    match_method: str | None = None
    administrative_area_code: str | None = None
    category: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class GeoResolution:
    status: str
    candidates: list[GeoCandidate]
    metadata: dict[str, Any]


class Geocoder(Protocol):
    def resolve(
        self,
        location_text: str,
        *,
        store_latitude: float | None = None,
        store_longitude: float | None = None,
        administrative_area_codes: list[str] | None = None,
        source_context: str | None = None,
        allow_administrative_fallback: bool = True,
    ) -> GeoResolution: ...

    def geocode(self, address: str) -> list[GeoCandidate]: ...


class MapApiGeocoder:
    def __init__(self, adapter: MapApiAdapter | None = None):
        self.adapter = adapter or MapApiAdapter()

    def resolve(
        self,
        location_text: str,
        *,
        store_latitude: float | None = None,
        store_longitude: float | None = None,
        administrative_area_codes: list[str] | None = None,
        source_context: str | None = None,
        allow_administrative_fallback: bool = True,
    ) -> GeoResolution:
        latitude, longitude, metadata = self.adapter.resolve_location(
            location_text,
            store_latitude=store_latitude,
            store_longitude=store_longitude,
            administrative_area_codes=administrative_area_codes,
            source_context=source_context,
            allow_administrative_fallback=allow_administrative_fallback,
        )
        candidates: list[GeoCandidate] = []
        if latitude is not None and longitude is not None and metadata.get("geocode_status") == "SUCCESS":
            candidates.append(GeoCandidate(
                address=str(metadata.get("matched_address") or location_text),
                latitude=float(latitude),
                longitude=float(longitude),
                provider=str(metadata.get("provider") or "") or None,
                match_method=str(metadata.get("match_type") or "") or None,
                administrative_area_code=(
                    str(metadata.get("administrative_area_code"))
                    if metadata.get("administrative_area_code") else None
                ),
                category=str(metadata.get("category") or "") or None,
                score=float(metadata.get("candidate_score") or 0),
            ))
        return GeoResolution(
            status=str(metadata.get("geocode_status") or "PROVIDER_ERROR"),
            candidates=candidates,
            metadata=metadata,
        )

    def geocode(self, address: str) -> list[GeoCandidate]:
        return self.resolve(address).candidates


class FakeGeocoder:
    def __init__(
        self,
        mapping: dict[str, list[GeoCandidate]],
        statuses: dict[str, str] | None = None,
        metadata: dict[str, dict[str, Any]] | None = None,
    ):
        self.mapping = mapping
        self.statuses = statuses or {}
        self.metadata = metadata or {}

    def resolve(
        self,
        location_text: str,
        *,
        store_latitude: float | None = None,
        store_longitude: float | None = None,
        administrative_area_codes: list[str] | None = None,
        source_context: str | None = None,
        allow_administrative_fallback: bool = True,
    ) -> GeoResolution:
        del store_latitude, store_longitude, administrative_area_codes
        del source_context, allow_administrative_fallback
        candidates = self.mapping.get(location_text, [])
        status = self.statuses.get(
            location_text,
            "SUCCESS" if len(candidates) == 1 else "AMBIGUOUS" if candidates else "NOT_FOUND",
        )
        metadata = {
            "geocode_status": status,
            "candidate_count": len(candidates),
            **self.metadata.get(location_text, {}),
        }
        return GeoResolution(status=status, candidates=candidates, metadata=metadata)

    def geocode(self, address: str) -> list[GeoCandidate]:
        return self.mapping.get(address, [])
