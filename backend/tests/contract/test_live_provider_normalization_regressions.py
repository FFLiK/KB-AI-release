import json
from pathlib import Path

from src.ingestion.official_api.kosis import KOSISAdapter
from src.ingestion.official_api.map_api import MapApiAdapter


FIXTURES = Path("tests/fixtures/providers")


def test_kakao_short_seoul_name_matches_canonical_query() -> None:
    response = json.loads(
        (FIXTURES / "geocoding/kakao_multiple_candidates.json").read_text(encoding="utf-8")
    )
    response["documents"][1]["road_address"]["address_name"] = "서울 강남구 테헤란로 152"

    latitude, longitude, metadata = MapApiAdapter().select_kakao_candidate(
        "서울특별시 강남구 테헤란로 152",
        response,
    )

    assert str(latitude) == "37.5007"
    assert str(longitude) == "127.0365"
    assert metadata["geocode_status"] == "SUCCESS"
    assert metadata["match_type"] == "EXACT_ROAD_ADDRESS"


def test_kosis_full_width_unit_label_matches_registered_series() -> None:
    rows = json.loads(
        (FIXTURES / "kosis/cpi_national_202505_202506.json").read_text(encoding="utf-8")
    )
    rows[0]["UNIT_NM"] = "2020＝100"

    observations = KOSISAdapter().normalize(rows)

    assert len(observations) == 2
    assert {item.unit for item in observations} == {"INDEX_2020_100"}
