# Phase 11.1 implementation note.
import hashlib
from typing import Dict, List, Tuple, Any

def generate_event_fingerprint(
    event_family: str,
    event_type: str,
    normalized_location: str,
    start_date_range: str,
    actor_org: str = "",
    target_subject: str = "",
) -> str:
    """Phase 11.1 documentation."""
    raw_key = f"{event_family.upper()}:{event_type.upper()}:{normalized_location.strip().lower()}:{start_date_range}:{actor_org.strip().lower()}:{target_subject.strip().lower()}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

def deduplicate_events(events: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Phase 11.2 documentation."""
    seen_fingerprints: Dict[str, Dict[str, Any]] = {}
    deduped_events: List[Dict[str, Any]] = []
    duplicate_events: List[Dict[str, Any]] = []

    for evt in events:
        fp = evt.get("fingerprint") or generate_event_fingerprint(
            event_family=evt.get("event_family", ""),
            event_type=evt.get("event_type", ""),
            normalized_location=evt.get("location_text_raw", ""),
            start_date_range=evt.get("start_date", ""),
        )
        evt["fingerprint"] = fp

        if fp in seen_fingerprints:
            # Implementation note.
            existing = seen_fingerprints[fp]
            existing["independent_source_count"] = existing.get("independent_source_count", 1) + 1
            duplicate_events.append(evt)
        else:
            evt["independent_source_count"] = 1
            seen_fingerprints[fp] = evt
            deduped_events.append(evt)

    return deduped_events, duplicate_events
