import json
import socket
import urllib.error
from pathlib import Path

import pytest

from src.ingestion.official_api.map_api import MapApiAdapter
from src.normalization.address_normalizer import normalize_korean_address


FIXTURES = Path("tests/fixtures/providers/geocoding")


class Response:
    status = 200

    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self.body


def payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_exact_road_match_wins_even_when_provider_returns_it_second() -> None:
    latitude, longitude, metadata = MapApiAdapter().select_kakao_candidate(
        "서울시 강남구 테헤란로 152",
        payload("kakao_multiple_candidates.json"),
    )

    assert str(latitude) == "37.5007" and str(longitude) == "127.0365"
    assert metadata["geocode_status"] == "SUCCESS"
    assert metadata["match_type"] == "EXACT_ROAD_ADDRESS"
    assert metadata["candidate_count"] == 2


def test_exact_lot_address_match_is_second_priority() -> None:
    latitude, longitude, metadata = MapApiAdapter().select_kakao_candidate(
        "서울특별시 강남구 역삼동 100",
        payload("kakao_lot_address.json"),
    )

    assert str(latitude) == "37.5007" and str(longitude) == "127.0365"
    assert metadata["match_type"] == "EXACT_LOT_ADDRESS"


def test_building_name_does_not_use_provider_order_as_a_tie_breaker() -> None:
    latitude, longitude, metadata = MapApiAdapter().select_kakao_candidate(
        "샘플빌딩",
        payload("kakao_ambiguous.json"),
    )

    assert latitude is None and longitude is None
    assert metadata["geocode_status"] == "AMBIGUOUS"
    assert metadata["reason"] == "NO_UNIQUE_EXACT_ADDRESS_MATCH"


def test_no_candidate_and_blank_address_are_explicit(monkeypatch) -> None:
    monkeypatch.setenv("KAKAO_REST_API_KEY", "configured-test-key")
    adapter = MapApiAdapter(opener=lambda *args, **kwargs: Response((FIXTURES / "kakao_empty.json").read_bytes()))

    latitude, longitude, metadata = adapter.geocode_address("서울특별시 강남구 없는로 999")
    assert latitude is None and longitude is None and metadata["geocode_status"] == "NOT_FOUND"
    latitude, longitude, metadata = adapter.geocode_address("  ")
    assert latitude is None and longitude is None and metadata["reason"] == "EMPTY_ADDRESS"


def test_successful_result_is_cached_by_normalized_query(monkeypatch) -> None:
    monkeypatch.setenv("KAKAO_REST_API_KEY", "configured-test-key")
    calls = 0

    def opener(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        return Response((FIXTURES / "kakao_lot_address.json").read_bytes())

    adapter = MapApiAdapter(opener=opener)
    first = adapter.geocode_address("서울시 강남구 테헤란로 152")
    second = adapter.geocode_address("서울특별시   강남구 테헤란로 152")

    assert first[2]["cache_hit"] is False
    assert second[2]["cache_hit"] is True
    assert first[:2] == second[:2] and calls == 1


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (urllib.error.HTTPError("https://provider.invalid", 401, "unauthorized", {}, None), "KAKAO_AUTHENTICATION_FAILED"),
        (urllib.error.HTTPError("https://provider.invalid", 403, "forbidden", {}, None), "KAKAO_NOT_AUTHORIZED"),
        (urllib.error.HTTPError("https://provider.invalid", 429, "limited", {}, None), "KAKAO_RATE_LIMITED"),
        (socket.timeout(), "KAKAO_TIMEOUT"),
    ],
)
def test_kakao_failures_have_safe_explicit_codes(monkeypatch, failure, reason) -> None:
    monkeypatch.setenv("KAKAO_REST_API_KEY", "configured-test-key")

    def opener(*args, **kwargs):
        del args, kwargs
        raise failure

    latitude, longitude, metadata = MapApiAdapter(opener=opener).geocode_address(
        "서울특별시 강남구 테헤란로 152"
    )
    assert latitude is None and longitude is None
    assert metadata["geocode_status"] == "PROVIDER_ERROR"
    assert metadata["reason"] == reason


def test_invalid_coordinate_order_or_bounds_is_rejected() -> None:
    invalid = payload("kakao_lot_address.json")
    invalid["documents"][0]["y"] = "127.0365"
    invalid["documents"][0]["x"] = "37.5007"

    latitude, longitude, metadata = MapApiAdapter().select_kakao_candidate(
        "서울특별시 강남구 테헤란로 152", invalid
    )

    assert latitude is None and longitude is None
    assert metadata["reason"] == "INVALID_COORDINATES"


def test_address_normalization_is_unicode_and_whitespace_stable() -> None:
    assert normalize_korean_address("  서울시  강남구, 테헤란로 152 ") == "서울특별시 강남구 테헤란로 152"


def test_placeholder_naver_credentials_never_trigger_fallback(monkeypatch) -> None:
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    monkeypatch.setenv("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "PLACEHOLDER")

    def opener(*args, **kwargs):
        del args, kwargs
        raise AssertionError("placeholder Naver credentials triggered a request")

    latitude, longitude, metadata = MapApiAdapter(opener=opener).geocode_address("서울특별시 강남구 테헤란로 152")
    assert latitude is None and longitude is None
    assert metadata["geocode_status"] == "NOT_CONFIGURED"
