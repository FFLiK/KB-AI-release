# Phase 12.3 implementation note.
from decimal import Decimal
from typing import Dict, Tuple, Optional, Any, List
from src.validation.geo_validator import evaluate_geo_exposure

def calculate_schedule_overlap(
    event_operating_hours: Optional[List[str]] = None,
    store_opening_hours: Optional[List[str]] = None,
) -> float:
    """Phase 12.3 documentation."""
    if not event_operating_hours or not store_opening_hours:
        return 1.0

    # Implementation note.
    try:
        s_start, s_end = int(store_opening_hours[0][:2]), int(store_opening_hours[1][:2])
        e_start, e_end = int(event_operating_hours[0][:2]), int(event_operating_hours[1][:2])
        
        overlap_start = max(s_start, e_start)
        overlap_end = min(s_end, e_end)

        if overlap_start >= overlap_end:
            return 0.0

        store_duration = s_end - s_start
        if store_duration <= 0:
            return 1.0

        return round((overlap_end - overlap_start) / float(store_duration), 4)
    except Exception:
        return 1.0

def calculate_exposure_score(
    store_lat: Optional[Decimal],
    store_lon: Optional[Decimal],
    event_lat: Optional[Decimal],
    event_lon: Optional[Decimal],
    temporal_overlap: float = 1.0,
    industry_relevance: float = 1.0,
    event_operating_hours: Optional[List[str]] = None,
    store_opening_hours: Optional[List[str]] = None,
    lambda_event_family: float = 500.0,
) -> Tuple[float, Dict[str, Any]]:
    """Phase 12.3 documentation."""
    geo_exp, metadata = evaluate_geo_exposure(
        store_lat, store_lon, event_lat, event_lon, lambda_event_family
    )

    if metadata.get("geo_status") == "EXCLUDED_DUE_TO_MISSING_GEO":
        return 0.0, metadata

    sched_overlap = calculate_schedule_overlap(event_operating_hours, store_opening_hours)
    metadata["schedule_overlap"] = sched_overlap
    metadata["temporal_overlap"] = temporal_overlap
    metadata["industry_relevance"] = industry_relevance

    total_exposure = geo_exp * temporal_overlap * industry_relevance * sched_overlap
    metadata["total_exposure"] = round(total_exposure, 4)

    return round(total_exposure, 4), metadata
