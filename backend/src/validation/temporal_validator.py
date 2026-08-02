# Phase 10.2 implementation note.
import calendar
from datetime import datetime
from typing import Tuple, Dict, Any, Optional

def calculate_temporal_overlap(
    event_start_str: str,  # YYYY-MM-DD
    event_end_str: Optional[str],  # YYYY-MM-DD
    target_month_str: str,  # YYYY-MM
) -> float:
    """Phase 12.3 documentation."""
    try:
        year, month = map(int, target_month_str.split("-"))
        _, days_in_month = calendar.monthrange(year, month)
        
        m_start = datetime(year, month, 1)
        m_end = datetime(year, month, days_in_month)

        evt_start = datetime.strptime(event_start_str[:10], "%Y-%m-%d")
        evt_end = datetime.strptime(event_end_str[:10], "%Y-%m-%d") if event_end_str else datetime(2099, 12, 31)

        overlap_start = max(m_start, evt_start)
        overlap_end = min(m_end, evt_end)

        if overlap_start > overlap_end:
            return 0.0

        overlap_days = (overlap_end - overlap_start).days + 1
        overlap_ratio = overlap_days / float(days_in_month)
        return round(max(0.0, min(1.0, overlap_ratio)), 4)
    except Exception:
        return 0.0

def validate_event_temporal(
    event_start_str: str,
    published_at_str: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Phase 10.2 documentation."""
    try:
        evt_start = datetime.strptime(event_start_str[:10], "%Y-%m-%d")
        if published_at_str:
            pub_dt = datetime.strptime(published_at_str[:10], "%Y-%m-%d")
            # Implementation note.
        return True, None
    except ValueError as e:
        return False, f"Invalid date string: {str(e)}"
