# Unit Tests for Step 4: Signals & Weight Aggregation Engine
from decimal import Decimal
import pytest

from src.signals.evidence_score import calculate_evidence_score
from src.signals.exposure_score import calculate_exposure_score, calculate_schedule_overlap
from src.signals.severity_registry import get_event_severity
from src.signals.aggregator import calculate_raw_signal, aggregate_signals_to_multiplier

def test_evidence_and_severity():
    """Phase 12.2 test."""
    ev_off = calculate_evidence_score("OFFICIAL_PRIMARY")
    assert ev_off == 1.0

    ev_news = calculate_evidence_score("SINGLE_NEWS")
    assert ev_news == 0.4

    sev_full = get_event_severity("PEDESTRIAN_FULL_CLOSURE")
    assert sev_full == 1.0


def test_schedule_and_exposure_overlap():
    """Phase 12.3 test."""
    # Step 1.
    sched = calculate_schedule_overlap(
        event_operating_hours=["12:00", "18:00"],
        store_opening_hours=["09:00", "22:00"],
    )
    assert 0.45 < sched < 0.47

    # Step 2.
    exp, meta = calculate_exposure_score(
        store_lat=Decimal("37.5665"),
        store_lon=Decimal("126.9780"),
        event_lat=None,
        event_lon=Decimal("127.0276"),
    )
    assert exp == 0.0
    assert meta["geo_status"] == "EXCLUDED_DUE_TO_MISSING_GEO"


def test_raw_signal_and_aggregator_clipping():
    """Phase 12.1 test."""
    # Step 1.
    sig, meta = calculate_raw_signal(
        direction=-1,
        source_tier="OFFICIAL_PRIMARY",
        store_lat=Decimal("37.5665"),
        store_lon=Decimal("126.9780"),
        event_lat=Decimal("37.5665"),
        event_lon=Decimal("126.9780"),
        event_type="PEDESTRIAN_FULL_CLOSURE",
    )
    assert sig == -1.0

    # Step 2.
    # Step 5.
    mult = aggregate_signals_to_multiplier(
        raw_signals=[sig] * 5,
        beta=-0.05,
        upper_bound=0.10,
    )
    # exp(0.10) ≈ 1.1052
    assert mult == Decimal("1.1052")
