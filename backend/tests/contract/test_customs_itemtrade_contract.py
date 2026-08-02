import socket
import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest

from src.ingestion.official_api.customs import CustomsAdapter


FIXTURE = Path("tests/fixtures/providers/customs/itemtrade_090111_202605_202606.xml")


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


def test_itemtrade_xml_replay_preserves_value_weight_and_derived_unit_price() -> None:
    adapter = CustomsAdapter()
    rows = adapter.parse(FIXTURE.read_bytes())
    observations = adapter.normalize(rows)

    assert len(rows) == 3
    assert len(observations) == 6
    assert {item.observed_at for item in observations} == {"2026-05-01", "2026-06-01"}
    assert {item.frequency for item in observations} == {"MONTHLY"}
    assert all(item.availability_policy_id == adapter.AVAILABILITY_POLICY_ID for item in observations)
    may = [item for item in observations if item.observed_at == "2026-05-01"]
    value = next(item for item in may if item.unit == "USD")
    weight = next(item for item in may if item.unit == "KG")
    unit_price = next(item for item in may if item.unit == "USD_PER_KG")
    assert Decimal(str(value.value)) == Decimal("80688299")
    assert Decimal(str(weight.value)) == Decimal("11411450")
    assert abs(Decimal(str(unit_price.value)) - Decimal("80688299") / Decimal("11411450")) < Decimal("1e-12")
    assert "IMPORT_VALUE" in value.indicator_id
    assert "IMPORT_UNIT_PRICE" in unit_price.indicator_id
    assert value.revision_id == weight.revision_id == unit_price.revision_id


def test_zero_or_missing_weight_never_creates_unit_price() -> None:
    adapter = CustomsAdapter()
    base = {
        "hsCode": "0901110000",
        "impDlr": "1000",
        "year": "2026.06",
    }
    zero = adapter.normalize([{**base, "impWgt": "0"}])
    missing = adapter.normalize([base])

    assert {item.unit for item in zero} == {"USD", "KG"}
    assert missing == []


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (urllib.error.HTTPError("https://provider.invalid", 401, "unauthorized", {}, None), "AUTHENTICATION_FAILED"),
        (urllib.error.HTTPError("https://provider.invalid", 403, "forbidden", {}, None), "AUTHENTICATION_FAILED"),
        (urllib.error.HTTPError("https://provider.invalid", 429, "limited", {}, None), "RATE_LIMITED"),
        (socket.timeout(), "TIMEOUT"),
    ],
)
def test_http_failures_are_explicit_and_fail_closed(monkeypatch, failure, expected) -> None:
    monkeypatch.setenv("CUSTOMS_API_KEY", "configured-test-key")

    def opener(*args, **kwargs):
        del args, kwargs
        raise failure

    adapter = CustomsAdapter(opener=opener)
    assert adapter.process({"strtYymm": "202605", "endYymm": "202606", "hsSgn": "090111"}) == []
    assert adapter.last_error_code == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"", "EMPTY_RESPONSE"),
        (b"<not-closed>", "MALFORMED_RESPONSE"),
        (b"<response><header><resultCode>30</resultCode></header></response>", "PROVIDER_RESULT_30"),
    ],
)
def test_payload_failures_are_explicit_and_fail_closed(monkeypatch, body, expected) -> None:
    monkeypatch.setenv("CUSTOMS_API_KEY", "configured-test-key")
    adapter = CustomsAdapter(opener=lambda *args, **kwargs: Response(body))
    assert adapter.process({"strtYymm": "202605", "endYymm": "202606", "hsSgn": "090111"}) == []
    assert adapter.last_error_code == expected


def test_placeholder_credential_never_reaches_opener(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOMS_API_KEY", "YOUR_CUSTOMS_API_KEY_HERE")

    def opener(*args, **kwargs):
        del args, kwargs
        raise AssertionError("placeholder credential triggered a request")

    adapter = CustomsAdapter(opener=opener)
    assert adapter.process({"strtYymm": "202605", "endYymm": "202606", "hsSgn": "090111"}) == []
    assert adapter.last_error_code == "NOT_CONFIGURED"
