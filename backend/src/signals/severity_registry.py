# Phase 12.4 implementation note.
from typing import Dict

SEVERITY_REGISTRY: Dict[str, float] = {
    "PEDESTRIAN_FULL_CLOSURE": 1.0,
    "PEDESTRIAN_PARTIAL_CLOSURE": 0.7,
    "VEHICLE_ONLY_RESTRICTION": 0.4,
    "EVENT_WITHOUT_DIRECT_MECHANISM": 0.0,
}

def get_event_severity(event_type: str) -> float:
    """Phase 12.4 documentation."""
    return SEVERITY_REGISTRY.get(event_type, 0.5)
