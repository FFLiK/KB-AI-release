import json
import socket
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ingestion.official_api.public_data import PublicDataStoreAdapter


FIXTURE = Path("tests/fixtures/providers/public_data/store_one_sample.json")


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


def test_store_one_replay_produces_entity_record_not_numeric_observation() -> None:
    adapter = PublicDataStoreAdapter()
    parsed = adapter.parse(FIXTURE.read_bytes())
    records = adapter.normalize(parsed)

    assert len(records) == 1
    record = records[0]
    assert record.business_id == "STORE-REF-SAMPLE-001"
    assert record.road_address == "서울특별시 강남구 테헤란로 152"
    assert record.latitude == 37.5007 and record.longitude == 127.0365
    assert record.provider_reference_month == "202607"
    assert not hasattr(record, "indicator_id") and not hasattr(record, "value")
    assert record.source_revision_id.startswith("SDSC-")


def test_store_snapshot_is_content_addressed_and_replay_stable(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_DATA_API_KEY", "configured-test-key")
    adapter = PublicDataStoreAdapter(opener=lambda *args, **kwargs: Response(FIXTURE.read_bytes()))
    retrieved_at = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

    first = adapter.build_snapshot({"endpoint": "storeOne", "key": "STORE-REF-SAMPLE-001"}, retrieved_at)
    second = adapter.build_snapshot({"endpoint": "storeOne", "key": "STORE-REF-SAMPLE-001"}, retrieved_at)

    assert first is not None and second is not None
    assert first == second
    assert first.snapshot_id.startswith("SRS-")
    assert first.body_hash == second.body_hash
    assert first.source_revision_id == first.records[0].source_revision_id
    assert first.raw_payload[0]["bizesId"] == "STORE-REF-SAMPLE-001"


@pytest.mark.parametrize(
    ("endpoint", "params", "expected_fields"),
    [
        ("storeOne", {"key": "SAMPLE"}, {"key"}),
        ("storeListInRadius", {"radius": 500, "cx": 127.0, "cy": 37.5}, {"radius", "cx", "cy"}),
        ("storeListInDong", {"divId": "adongCd", "key": "11680640"}, {"divId", "key"}),
        ("storeListInUpjong", {"divId": "indsSclsCd", "key": "I21201"}, {"divId", "key"}),
        ("storeListByDate", {"startDate": "20260701", "endDate": "20260731"}, {"startDate", "endDate"}),
    ],
)
def test_supported_endpoint_request_contracts(monkeypatch, endpoint, params, expected_fields) -> None:
    monkeypatch.setenv("PUBLIC_DATA_API_KEY", "configured-test-key")
    captured = {}

    def opener(request, timeout):
        captured["path"] = urllib.parse.urlparse(request.full_url).path
        captured["query"] = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        assert timeout == 15
        return Response(FIXTURE.read_bytes())

    records = PublicDataStoreAdapter(opener=opener).process({"endpoint": endpoint, **params})

    assert len(records) == 1
    assert captured["path"].endswith("/" + endpoint)
    assert expected_fields <= set(captured["query"])
    assert set(captured["query"]) <= expected_fields | {"serviceKey", "type"}


def test_unknown_endpoint_and_extra_fields_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_DATA_API_KEY", "configured-test-key")
    adapter = PublicDataStoreAdapter(opener=lambda *args, **kwargs: Response(FIXTURE.read_bytes()))

    assert adapter.process({"endpoint": "arbitrary", "key": "SAMPLE"}) == []
    assert adapter.last_error_code == "UNSUPPORTED_ENDPOINT"
    assert adapter.process({"endpoint": "storeOne", "key": "SAMPLE", "guess": "field"}) == []
    assert adapter.last_error_code == "INVALID_REQUEST"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (urllib.error.HTTPError("https://provider.invalid", 401, "unauthorized", {}, None), "AUTHENTICATION_FAILED"),
        (urllib.error.HTTPError("https://provider.invalid", 429, "limited", {}, None), "RATE_LIMITED"),
        (socket.timeout(), "TIMEOUT"),
    ],
)
def test_public_store_network_failures_are_explicit(monkeypatch, failure, expected) -> None:
    monkeypatch.setenv("PUBLIC_DATA_API_KEY", "configured-test-key")

    def opener(*args, **kwargs):
        del args, kwargs
        raise failure

    adapter = PublicDataStoreAdapter(opener=opener)
    assert adapter.process({"endpoint": "storeOne", "key": "SAMPLE"}) == []
    assert adapter.last_error_code == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"", "EMPTY_RESPONSE"),
        (b"not-json", "MALFORMED_RESPONSE"),
        (b'{"header":{"resultCode":"30"},"body":{}}', "AUTHENTICATION_FAILED"),
        (b'{"header":{"resultCode":"22"},"body":{}}', "RATE_LIMITED"),
        (b'{"header":{"resultCode":"00"},"body":{"items":[]}}', "MISSING_REFERENCE_MONTH"),
        (b'<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>', "AUTHENTICATION_FAILED"),
    ],
)
def test_public_store_payload_failures_are_explicit(monkeypatch, payload, expected) -> None:
    monkeypatch.setenv("PUBLIC_DATA_API_KEY", "configured-test-key")
    adapter = PublicDataStoreAdapter(opener=lambda *args, **kwargs: Response(payload))
    assert adapter.process({"endpoint": "storeOne", "key": "SAMPLE"}) == []
    assert adapter.last_error_code == expected


def test_invalid_record_coordinates_are_rejected() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["body"]["items"][0]["lat"] = 137.5
    adapter = PublicDataStoreAdapter()
    assert adapter.normalize(adapter.parse(json.dumps(payload).encode())) == []


def test_placeholder_credential_never_reaches_public_data_opener(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_DATA_API_KEY", "CHANGE_ME")

    def opener(*args, **kwargs):
        del args, kwargs
        raise AssertionError("placeholder credential triggered a request")

    adapter = PublicDataStoreAdapter(opener=opener)
    assert adapter.process({"endpoint": "storeOne", "key": "SAMPLE"}) == []
    assert adapter.last_error_code == "NOT_CONFIGURED"
