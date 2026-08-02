import json
import socket
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from src.ingestion.official_api.kosis import KOSISAdapter


FIXTURE = Path("tests/fixtures/providers/kosis/cpi_national_202505_202506.json")


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


def test_kosis_sanitized_replay_is_bound_to_exact_national_cpi_series() -> None:
    adapter = KOSISAdapter()
    observations = adapter.normalize(adapter.parse(FIXTURE.read_bytes()))

    assert len(observations) == 2
    assert [item.value for item in observations] == [116.27, 116.31]
    assert [item.observed_at for item in observations] == ["2025-05-01", "2025-06-01"]
    assert [item.available_at for item in observations] == [
        "2025-06-04T00:00:00+09:00",
        "2025-07-02T00:00:00+09:00",
    ]
    assert {item.indicator_id for item in observations} == {"CONSUMER_PRICE_INDEX"}
    assert {item.unit for item in observations} == {"INDEX_2020_100"}
    assert all(item.revision_id and item.source_id.startswith("SRC-KOSIS-") for item in observations)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("ORG_ID", "999"),
        ("TBL_ID", "OTHER"),
        ("ITM_ID", "OTHER"),
        ("C1_NM", "서울특별시"),
        ("PRD_SE", "Q"),
        ("UNIT_NM", "2015=100"),
        ("LST_CHN_DE", ""),
    ],
)
def test_kosis_rejects_unregistered_or_unavailable_dimensions(field, replacement) -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows[0][field] = replacement
    observations = KOSISAdapter().normalize(rows)
    assert len(observations) == 1
    assert observations[0].observed_at == "2025-06-01"


def test_kosis_fetch_uses_official_parameter_contract(monkeypatch) -> None:
    monkeypatch.setenv("KOSIS_API_KEY", "configured-test-key")
    captured = {}

    def opener(request, timeout):
        captured.update(urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query))
        assert timeout == 15
        return Response(FIXTURE.read_bytes())

    params = {
        "orgId": "101",
        "tblId": "DT_1J22003",
        "objL1": "ALL",
        "itmId": "T",
        "prdSe": "M",
        "startPrdDe": "202505",
        "endPrdDe": "202506",
    }
    observations = KOSISAdapter(opener=opener).process(params)

    assert len(observations) == 2
    assert set(captured) == {
        "method", "apiKey", "orgId", "tblId", "objL1", "itmId", "prdSe",
        "startPrdDe", "endPrdDe", "format", "jsonVD",
    }
    assert "userStatsId" not in captured and captured["objL1"] == ["ALL"]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (urllib.error.HTTPError("https://provider.invalid", 401, "unauthorized", {}, None), "AUTHENTICATION_FAILED"),
        (urllib.error.HTTPError("https://provider.invalid", 429, "limited", {}, None), "RATE_LIMITED"),
        (socket.timeout(), "TIMEOUT"),
    ],
)
def test_kosis_network_failures_are_explicit(monkeypatch, failure, expected) -> None:
    monkeypatch.setenv("KOSIS_API_KEY", "configured-test-key")

    def opener(*args, **kwargs):
        del args, kwargs
        raise failure

    adapter = KOSISAdapter(opener=opener)
    assert adapter.process({
        "orgId": "101", "tblId": "DT_1J22003", "objL1": "ALL", "itmId": "T",
        "prdSe": "M", "startPrdDe": "202505", "endPrdDe": "202506",
    }) == []
    assert adapter.last_error_code == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"", "EMPTY_RESPONSE"),
        (b"not-json", "MALFORMED_RESPONSE"),
        (b'{"err":"11","errMsg":"rejected"}', "AUTHENTICATION_FAILED"),
        (b'{"err":"20","errMsg":"invalid request"}', "PROVIDER_RESULT_20"),
        (b'{"unexpected":true}', "MALFORMED_RESPONSE"),
    ],
)
def test_kosis_payload_failures_are_explicit(payload, expected) -> None:
    adapter = KOSISAdapter()
    if not payload:
        assert adapter.parse(payload) == []
        return
    with pytest.raises(Exception) as caught:
        adapter.parse(payload)
    assert getattr(caught.value, "code", None) == expected


def test_placeholder_credential_never_reaches_kosis_opener(monkeypatch) -> None:
    monkeypatch.setenv("KOSIS_API_KEY", "YOUR_KOSIS_API_KEY_HERE")

    def opener(*args, **kwargs):
        del args, kwargs
        raise AssertionError("placeholder credential triggered a request")

    adapter = KOSISAdapter(opener=opener)
    assert adapter.process({}) == []
    assert adapter.last_error_code == "NOT_CONFIGURED"
