import json
import socket
import urllib.error
from pathlib import Path

import pytest

from src.ingestion.official_api.ecos import ECOSAdapter


FIXTURES = Path("tests/fixtures/providers/ecos")
CASES = (
    ("base_rate_202605_202606.json", "BASE_RATE", "PERCENT", "ECOS_MONTH_END_PLUS_10D_APPROX.v1"),
    ("usd_krw_average_202605_202606.json", "USD_KRW", "KRW_PER_USD", "ECOS_MONTH_END_PLUS_10D_APPROX.v1"),
    ("import_price_usd_202605_202606.json", "IMPORT_PRICE_INDEX_USD", "INDEX_2020_100", "ECOS_MONTH_END_PLUS_20D_APPROX.v1"),
)


@pytest.mark.parametrize(("filename", "indicator", "unit", "policy"), CASES)
def test_ecos_sanitized_replay_is_bound_to_exact_series(filename, indicator, unit, policy) -> None:
    adapter = ECOSAdapter()
    rows = adapter.parse((FIXTURES / filename).read_bytes())
    observations = adapter.normalize(rows)

    assert len(observations) == 2
    assert {item.indicator_id for item in observations} == {indicator}
    assert {item.unit for item in observations} == {unit}
    assert {item.frequency for item in observations} == {"MONTHLY"}
    assert [item.observed_at for item in observations] == ["2026-05-01", "2026-06-01"]
    assert all(item.availability_policy_id == policy for item in observations)
    assert all(item.revision_id and item.source_id.startswith("SRC-ECOS-") for item in observations)


def test_ecos_rejects_unregistered_dimensions_instead_of_guessing() -> None:
    payload = json.loads((FIXTURES / "usd_krw_average_202605_202606.json").read_text(encoding="utf-8"))
    payload["StatisticSearch"]["row"][0]["ITEM_CODE2"] = "0000200"
    adapter = ECOSAdapter()

    observations = adapter.normalize(payload["StatisticSearch"]["row"])

    assert len(observations) == 1
    assert observations[0].observed_at == "2026-06-01"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (urllib.error.HTTPError("https://provider.invalid", 401, "unauthorized", {}, None), "AUTHENTICATION_FAILED"),
        (urllib.error.HTTPError("https://provider.invalid", 429, "limited", {}, None), "RATE_LIMITED"),
        (socket.timeout(), "TIMEOUT"),
    ],
)
def test_ecos_network_failures_are_explicit(monkeypatch, failure, expected) -> None:
    monkeypatch.setenv("ECOS_API_KEY", "configured-test-key")

    def opener(*args, **kwargs):
        del args, kwargs
        raise failure

    adapter = ECOSAdapter(opener=opener)
    assert adapter.process({
        "stat_code": "722Y001",
        "period_type": "M",
        "start_date": "202605",
        "end_date": "202606",
        "item_code": "0101000",
    }) == []
    assert adapter.last_error_code == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"", "EMPTY_RESPONSE"),
        (b"not-json", "MALFORMED_RESPONSE"),
        (b'{"RESULT":{"CODE":"ERROR-301"}}', "PROVIDER_RESULT_ERROR-301"),
    ],
)
def test_ecos_payload_failures_are_explicit(payload, expected) -> None:
    adapter = ECOSAdapter()
    if payload:
        with pytest.raises(Exception) as caught:
            adapter.parse(payload)
        assert getattr(caught.value, "code", None) == expected
    else:
        assert adapter.parse(payload) == []
