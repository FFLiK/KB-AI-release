from datetime import date

import pytest

from src.config.credential_validation import get_credential
from src.ingestion.official_api.customs import CustomsAdapter
from src.orchestration.official_data_pipeline import OfficialDataPipeline
from src.contracts.official import OfficialDataRequest


pytestmark = pytest.mark.live


def test_customs_itemtrade_live_smoke_and_official_bundle() -> None:
    if not (get_credential("CUSTOMS_API_KEY") or get_credential("DATA_GO_KR_API_KEY")):
        pytest.skip("Customs credential is not configured")
    adapter = CustomsAdapter()
    indicator = "CUSTOMS_IMPORT_UNIT_PRICE_USD_PER_KG_HS0901110000"
    request_params = {
        "strtYymm": "202605",
        "endYymm": "202606",
        "hsSgn": "090111",
        "indicator_id": indicator,
    }

    observations = adapter.process(request_params)

    if adapter.last_error_code in {"AUTHENTICATION_FAILED", "HTTP_ERROR", "SERVICE_ERROR"}:
        pytest.skip(f"Customs API key authentication or service error: {adapter.last_error_code}")

    assert adapter.last_error_code is None
    assert len(observations) >= 2
    assert all(item.indicator_id == indicator for item in observations)
    assert all(item.unit == "USD_PER_KG" and item.value > 0 for item in observations)

    bundle = OfficialDataPipeline({"CUSTOMS": adapter}).run(
        "LIVE-CUSTOMS-CONTRACT",
        date(2026, 7, 31),
        [OfficialDataRequest(
            provider="CUSTOMS",
            indicator_id=indicator,
            request_params=request_params,
            required=True,
            max_age_days=120,
        )],
    )
    assert len(bundle.observations) >= 2
    assert not bundle.missing_indicators
