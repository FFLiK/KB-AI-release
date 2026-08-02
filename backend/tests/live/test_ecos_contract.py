from datetime import date

import pytest

from src.config.credential_validation import get_credential
from src.contracts.official import OfficialDataRequest
from src.ingestion.official_api.ecos import ECOSAdapter
from src.orchestration.official_data_pipeline import OfficialDataPipeline


pytestmark = pytest.mark.live

CASES = (
    ("BASE_RATE", "722Y001", "0101000", None, "PERCENT"),
    ("USD_KRW", "731Y004", "0000001", "0000100", "KRW_PER_USD"),
    ("IMPORT_PRICE_INDEX_USD", "401Y015", "*AA", "D", "INDEX_2020_100"),
)


@pytest.mark.parametrize(("indicator", "stat_code", "item_code", "item_code2", "unit"), CASES)
def test_ecos_live_registered_series_reaches_official_bundle(
    indicator, stat_code, item_code, item_code2, unit
) -> None:
    if not get_credential("ECOS_API_KEY"):
        pytest.skip("ECOS credential is not configured")
    adapter = ECOSAdapter()
    params = {
        "stat_code": stat_code,
        "period_type": "M",
        "start_date": "202605",
        "end_date": "202606",
        "item_code": item_code,
        "indicator_id": indicator,
    }
    if item_code2:
        params["item_code2"] = item_code2

    normalized = adapter.process(params)

    assert adapter.last_error_code is None
    assert len(normalized) == 2
    assert all(item.indicator_id == indicator and item.unit == unit for item in normalized)

    bundle = OfficialDataPipeline({"ECOS": adapter}).run(
        f"LIVE-ECOS-{indicator}",
        date(2026, 7, 31),
        [OfficialDataRequest(
            provider="ECOS",
            indicator_id=indicator,
            request_params=params,
            required=True,
            max_age_days=120,
        )],
    )
    assert len(bundle.observations) == 2
    assert all(item.availability_policy_id for item in bundle.observations)
