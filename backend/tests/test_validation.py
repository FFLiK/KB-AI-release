# Unit Tests for Step 2: Input Parsing & Validation Pipeline
from decimal import Decimal
import pytest

from src.ingestion.user_input.parser import parse_and_validate_csv_input
from src.validation.state_machine import EventValidationState, EventValidationContext, transition_event_state
from src.validation.schema_validator import validate_event_schema
from src.validation.evidence_validator import validate_event_evidence, normalize_text
from src.validation.temporal_validator import calculate_temporal_overlap, validate_event_temporal
from src.validation.geo_validator import calculate_haversine_distance_meters, evaluate_geo_exposure
from src.validation.deduplicator import generate_event_fingerprint, deduplicate_events
from src.validation.conflict_resolver import assign_cause_group_id

def test_csv_parser_valid_and_errors():
    """Phase 6 test."""
    # Step 1.
    valid_rows = [
        {"month": "2026-06", "revenue_krw": "30000000", "variable_costs_krw": "12000000", "fixed_costs_krw": "10000000"},
        {"month": "2026-07", "revenue_krw": "32000000", "variable_costs_krw": "13000000", "fixed_costs_krw": "10000000"},
    ]
    res_ok = parse_and_validate_csv_input(valid_rows)
    assert res_ok.is_valid is True
    assert len(res_ok.data["monthly_history"]) == 2

    # Step 2.
    dup_rows = [
        {"month": "2026-06", "revenue_krw": "30000000", "variable_costs_krw": "12000000", "fixed_costs_krw": "10000000"},
        {"month": "2026-06", "revenue_krw": "32000000", "variable_costs_krw": "13000000", "fixed_costs_krw": "10000000"},
    ]
    res_dup = parse_and_validate_csv_input(dup_rows)
    assert res_dup.is_valid is False
    assert any(e.step == "TIMESERIES_CONTINUITY" for e in res_dup.errors)

    # Step 3.
    mismatch_rows = [
        {
            "month": "2026-06",
            "revenue_krw": "30000000",
            "variable_costs_krw": "12000000",
            "fixed_costs_krw": "10000000",
            "ingredients_krw": "5000000",
            "platform_fee_krw": "5000000",  # Implementation note.
        }
    ]
    res_sum = parse_and_validate_csv_input(mismatch_rows)
    assert res_sum.is_valid is False
    assert any(e.step == "ACCOUNTING_SUM" for e in res_sum.errors)


def test_schema_validator():
    """Phase 10.2 test."""
    valid_evt = {
        "event_id": "EVT-001",
        "domain": "LOCAL",
        "event_family": "ACCESSIBILITY",
        "event_type": "PEDESTRIAN_PARTIAL_CLOSURE",
        "direction": "NEGATIVE",
        "start_date": "2026-08-01",
        "end_date": "2026-09-15",
    }
    is_ok, errors = validate_event_schema(valid_evt)
    assert is_ok is True

    # Implementation note.
    invalid_date_evt = dict(valid_evt, start_date="2026-09-30", end_date="2026-08-01")
    is_ok, errors = validate_event_schema(invalid_date_evt)
    assert is_ok is False
    assert any("Invalid date order" in err for err in errors)


def test_evidence_validator():
    """Phase 10.2 test."""
    body = "공사 기간 중 보행로 일부를 통제합니다. 주의하시기 바랍니다."
    snapshots = {"SRC-NEWS-001": body}

    valid_ev = [
        {
            "source_id": "SRC-NEWS-001",
            "quote": "보행로 일부를 통제합니다.",
            "start_offset": 8,
            "end_offset": 23,
        }
    ]
    is_ok, errors = validate_event_evidence(valid_ev, snapshots)
    assert is_ok is True

    # Implementation note.
    mismatch_ev = [
        {
            "source_id": "SRC-NEWS-001",
            "quote": "도로를 완전 차단합니다.",
            "start_offset": 8,
            "end_offset": 23,
        }
    ]
    is_ok, errors = validate_event_evidence(mismatch_ev, snapshots)
    assert is_ok is False


def test_temporal_overlap():
    """Phase 10.2 test."""
    # Implementation note.
    ratio = calculate_temporal_overlap(
        event_start_str="2026-08-15",
        event_end_str="2026-08-31",
        target_month_str="2026-08",
    )
    # 17 / 31 = 0.548387... -> 0.5484
    assert 0.54 < ratio < 0.55


def test_validation_state_machine():
    """Phase 10.1 test."""
    ctx = EventValidationContext(event_id="EVT-101")
    assert ctx.current_state == EventValidationState.DISCOVERED

    ctx = transition_event_state(ctx, EventValidationState.SCHEMA_VALIDATED, reason="Schema OK")
    assert ctx.current_state == EventValidationState.SCHEMA_VALIDATED
    assert len(ctx.history) == 1
    assert ctx.history[0].reason == "Schema OK"


def test_haversine_and_geo_exposure_missing():
    """Phase 10.2 test."""
    dist = calculate_haversine_distance_meters(37.5665, 126.9780, 37.4979, 127.0276)
    assert 8000 < dist < 9500

    exp, meta = evaluate_geo_exposure(
        store_lat=Decimal("37.5665"),
        store_lon=Decimal("126.9780"),
        event_lat=None,
        event_lon=Decimal("127.0276"),
    )
    assert exp == 0.0
    assert meta["geo_status"] == "EXCLUDED_DUE_TO_MISSING_GEO"


def test_deduplicator_and_cause_group():
    """Phase 11 test."""
    evts = [
        {"event_id": "E1", "event_family": "LOCAL", "event_type": "ROAD_WORK", "location_text_raw": "Gangnam", "start_date": "2026-08-01"},
        {"event_id": "E2", "event_family": "LOCAL", "event_type": "ROAD_WORK", "location_text_raw": "Gangnam", "start_date": "2026-08-01"},
    ]
    deduped, dups = deduplicate_events(evts)
    assert len(deduped) == 1
    assert len(dups) == 1
    assert deduped[0]["independent_source_count"] == 2

    grouped = assign_cause_group_id(deduped)
    assert "cause_group_id" in grouped[0]
