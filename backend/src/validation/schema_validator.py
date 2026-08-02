# Phase 10.2 implementation note.
from typing import Dict, Any, Tuple, List
from datetime import datetime

ALLOWED_DOMAINS = {"MACRO", "INDUSTRY", "LOCAL", "POLICY"}
ALLOWED_DIRECTIONS = {"POSITIVE", "NEGATIVE", "NEUTRAL"}
REQUIRED_EVENT_FIELDS = ["event_id", "domain", "event_family", "event_type", "direction", "start_date"]

def validate_event_schema(event_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Phase 10.2 documentation."""
    errors: List[str] = []

    # Step 1.
    for field in REQUIRED_EVENT_FIELDS:
        if field not in event_data or event_data[field] is None or str(event_data[field]).strip() == "":
            errors.append(f"Missing required field: '{field}'")

    if errors:
        return False, errors

    # Step 2.
    domain = str(event_data.get("domain", "")).upper()
    if domain not in ALLOWED_DOMAINS:
        errors.append(f"Invalid domain '{domain}'. Must be one of {ALLOWED_DOMAINS}")

    direction = str(event_data.get("direction", "")).upper()
    if direction not in ALLOWED_DIRECTIONS and direction not in ["-1", "0", "1"]:
        errors.append(f"Invalid direction '{direction}'. Must be POSITIVE, NEGATIVE, or NEUTRAL")

    # Step 3.
    start_date_str = str(event_data.get("start_date", "")).strip()
    end_date_str = str(event_data.get("end_date", "")).strip() if event_data.get("end_date") else None

    if start_date_str:
        try:
            start_dt = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
            if end_date_str:
                end_dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
                if start_dt > end_dt:
                    errors.append(f"Invalid date order: start_date ({start_date_str}) > end_date ({end_date_str})")
        except ValueError as e:
            errors.append(f"Invalid date format: {str(e)}")

    return len(errors) == 0, errors
