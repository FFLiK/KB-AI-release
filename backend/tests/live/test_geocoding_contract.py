from decimal import Decimal

import pytest

from src.config.credential_validation import get_credential
from src.ingestion.official_api.map_api import MapApiAdapter


pytestmark = pytest.mark.live


def test_primary_sample_address_live_geocoding_contract() -> None:
    if not get_credential("KAKAO_REST_API_KEY"):
        pytest.skip("Kakao REST credential is not configured")
    latitude, longitude, metadata = MapApiAdapter().geocode_address(
        "서울특별시 강남구 테헤란로 152"
    )
    assert metadata["geocode_status"] == "SUCCESS"
    assert latitude is not None and longitude is not None
    assert Decimal("33") <= latitude <= Decimal("39")
    assert Decimal("124") <= longitude <= Decimal("132")
