from decimal import Decimal

import pytest

from src.validation.geo_validator import (
    calculate_haversine_distance_meters,
    evaluate_geo_exposure,
)


def test_one_degree_at_equator_matches_independent_reference() -> None:
    distance = calculate_haversine_distance_meters(0.0, 0.0, 0.0, 1.0)
    assert distance == pytest.approx(111_194.9266, abs=0.01)
    assert distance == pytest.approx(calculate_haversine_distance_meters(0.0, 1.0, 0.0, 0.0), abs=1e-9)


@pytest.mark.parametrize(
    "coordinates",
    [(91.0, 0.0, 0.0, 0.0), (0.0, 181.0, 0.0, 0.0), (0.0, 0.0, -91.0, 0.0)],
)
def test_haversine_rejects_invalid_coordinate_bounds(coordinates) -> None:
    with pytest.raises(ValueError):
        calculate_haversine_distance_meters(*coordinates)


def test_geo_exposure_labels_straight_line_distance_and_rejects_invalid() -> None:
    exposure, metadata = evaluate_geo_exposure(
        Decimal("37.5007"), Decimal("127.0365"), Decimal("37.5010"), Decimal("127.0370")
    )
    assert 0 < exposure < 1
    assert metadata["distance_type"] == "STRAIGHT_LINE_HAVERSINE"

    exposure, metadata = evaluate_geo_exposure(
        Decimal("137.5"), Decimal("127.0"), Decimal("37.5"), Decimal("127.0")
    )
    assert exposure == 0
    assert metadata["geo_status"] == "EXCLUDED_DUE_TO_INVALID_GEO"
