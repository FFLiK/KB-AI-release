# Phase 12.1 implementation note.
from decimal import Decimal
import math
from typing import Dict, List, Any, Tuple, Optional

from src.signals.evidence_score import calculate_evidence_score
from src.signals.exposure_score import calculate_exposure_score
from src.signals.severity_registry import get_event_severity
from src.signals.coefficient_registry import get_coefficient

def calculate_raw_signal(
    direction: int,  # Implementation note.
    source_tier: str,
    store_lat: Any,
    store_lon: Any,
    event_lat: Any,
    event_lon: Any,
    event_type: str,
    temporal_overlap: float = 1.0,
    industry_relevance: float = 1.0,
    event_operating_hours: Optional[List[str]] = None,
    store_opening_hours: Optional[List[str]] = None,
    time_decay: float = 1.0,
) -> Tuple[float, Dict[str, Any]]:
    """
    Phase 12.1: RawSignal = Direction * Evidence * Exposure * Severity * TimeDecay
    """
    evidence = calculate_evidence_score(source_tier=source_tier)
    exposure, geo_meta = calculate_exposure_score(
        store_lat=store_lat,
        store_lon=store_lon,
        event_lat=event_lat,
        event_lon=event_lon,
        temporal_overlap=temporal_overlap,
        industry_relevance=industry_relevance,
        event_operating_hours=event_operating_hours,
        store_opening_hours=store_opening_hours,
    )
    severity = get_event_severity(event_type=event_type)

    raw_signal = float(direction) * evidence * exposure * severity * time_decay
    metadata = {
        "evidence_score": evidence,
        "exposure_score": exposure,
        "severity_score": severity,
        "raw_signal": round(raw_signal, 4),
    }
    metadata.update(geo_meta)

    return round(raw_signal, 4), metadata

def aggregate_signals_to_multiplier(
    raw_signals: List[float],
    beta: float = -0.05,
    lower_bound: float = -0.30,
    upper_bound: float = 0.30,
) -> Decimal:
    """
    Phase 12.6: AxisShock = clip(sum(Shock), lower_bound, upper_bound)
    RevenueMultiplier = exp(AxisShock)
    """
    if not raw_signals:
        return Decimal("1.0")

    shocks = [s * beta for s in raw_signals]
    total_shock = sum(shocks)

    clipped_shock = max(lower_bound, min(upper_bound, total_shock))
    multiplier_float = math.exp(clipped_shock)

    return Decimal(str(round(multiplier_float, 4)))
