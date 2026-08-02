# Phase 10.2 implementation note.
import unicodedata
from typing import Dict, List, Any, Tuple

def normalize_text(text: str) -> str:
    """Documentation."""
    nfkc = unicodedata.normalize("NFKC", text)
    return " ".join(nfkc.split())

def validate_event_evidence(
    evidence_list: List[Dict[str, Any]],
    source_snapshots: Dict[str, str],  # source_id -> body_text
) -> Tuple[bool, List[str]]:
    """Phase 10.2 documentation."""
    errors: List[str] = []

    if not evidence_list:
        errors.append("Evidence list is empty. At least one valid evidence quote is required.")
        return False, errors

    for idx, ev in enumerate(evidence_list):
        source_id = ev.get("source_id")
        if not source_id:
            errors.append(f"Evidence [{idx}]: Missing source_id")
            continue

        body_text = source_snapshots.get(source_id)
        if not body_text:
            errors.append(f"Evidence [{idx}]: Source snapshot not found for source_id '{source_id}'")
            continue

        quote = ev.get("quote", "")
        if not quote:
            errors.append(f"Evidence [{idx}]: Empty quote string")
            continue

        start_offset = ev.get("start_offset")
        end_offset = ev.get("end_offset")

        # Implementation note.
        if start_offset is not None and end_offset is not None:
            if start_offset < 0 or end_offset > len(body_text) or start_offset >= end_offset:
                errors.append(f"Evidence [{idx}]: Invalid offset range [{start_offset}:{end_offset}] for body length {len(body_text)}")
            else:
                extracted_slice = body_text[start_offset:end_offset]
                if normalize_text(extracted_slice) != normalize_text(quote):
                    errors.append(f"Evidence [{idx}]: Offset slice '{extracted_slice}' does not match quote '{quote}'")

        # Implementation note.
        if normalize_text(quote) not in normalize_text(body_text):
            errors.append(f"Evidence [{idx}]: Quote '{quote}' not found in source body_text")

    return len(errors) == 0, errors
