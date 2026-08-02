from datetime import date

import pytest

from src.config.credential_validation import get_credential
from src.contracts.official import OfficialDataRequest
from src.ingestion.official_api.kosis import KOSISAdapter
from src.orchestration.official_data_pipeline import OfficialDataPipeline


pytestmark = pytest.mark.live


def test_kosis_live_registered_series_reaches_official_bundle() -> None:
    if not get_credential("KOSIS_API_KEY"):
        pytest.skip("KOSIS credential is not configured")
    adapter = KOSISAdapter()
    params = {
        "orgId": "101",
        "tblId": "DT_1J22003",
        "objL1": "ALL",
        "itmId": "T",
        "prdSe": "M",
        "startPrdDe": "202505",
        "endPrdDe": "202506",
        "indicator_id": "CONSUMER_PRICE_INDEX",
    }

    observations = adapter.process(params)
    assert adapter.last_error_code is None
    assert len(observations) == 2
    assert all(item.indicator_id == "CONSUMER_PRICE_INDEX" for item in observations)
    bundle = OfficialDataPipeline({"KOSIS": adapter}).run(
        "LIVE-KOSIS-CPI",
        date(2025, 7, 31),
        [OfficialDataRequest(
            provider="KOSIS",
            indicator_id="CONSUMER_PRICE_INDEX",
            request_params=params,
            required=True,
            max_age_days=120,
        )],
    )
    assert len(bundle.observations) == 2
    assert not bundle.missing_indicators
