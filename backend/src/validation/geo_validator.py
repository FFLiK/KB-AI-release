from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

EARTH_RADIUS_METERS = 6_371_000.0


def validate_coordinate_pair(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90):
        raise ValueError("latitude must be between -90 and 90")
    if not (-180 <= longitude <= 180):
        raise ValueError("longitude must be between -180 and 180")


def calculate_haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate straight-line great-circle distance, never route distance."""
    validate_coordinate_pair(lat1, lon1)
    validate_coordinate_pair(lat2, lon2)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


def evaluate_geo_exposure(
    store_lat: Optional[Decimal],
    store_lon: Optional[Decimal],
    event_lat: Optional[Decimal],
    event_lon: Optional[Decimal],
    lambda_event_family: float = 500.0,
) -> Tuple[float, Dict[str, Any]]:
    metadata: Dict[str, Any] = {}
    if store_lat is None or store_lon is None or event_lat is None or event_lon is None:
        metadata["geo_status"] = "EXCLUDED_DUE_TO_MISSING_GEO"
        metadata["reason"] = "Missing store or event coordinates"
        return 0.0, metadata
    try:
        distance_m = calculate_haversine_distance_meters(
            float(store_lat), float(store_lon), float(event_lat), float(event_lon)
        )
    except ValueError:
        return 0.0, {"geo_status": "EXCLUDED_DUE_TO_INVALID_GEO", "reason": "Invalid coordinate bounds"}
    geo_exposure = math.exp(-distance_m / lambda_event_family)
    metadata["geo_status"] = "CALCULATED"
    metadata["distance_meters"] = round(distance_m, 2)
    metadata["distance_type"] = "STRAIGHT_LINE_HAVERSINE"
    return geo_exposure, metadata
