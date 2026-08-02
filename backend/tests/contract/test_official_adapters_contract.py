"""Offline parser and fail-closed contracts for official provider adapters."""

from src.ingestion.official_api.customs import CustomsAdapter
from src.ingestion.official_api.ecos import ECOSAdapter
from src.ingestion.official_api.kosis import KOSISAdapter
from src.ingestion.official_api.map_api import MapApiAdapter
from src.ingestion.official_api.public_data import PublicDataStoreAdapter


def test_ecos_adapter_fails_closed_without_credentials_and_parses_fixture() -> None:
    adapter = ECOSAdapter()
    assert adapter.process({"stat_code": "722Y001"}) == []

    raw = [{
        "TIME": "202607",
        "DATA_VALUE": "3.50",
        "STAT_CODE": "722Y001",
        "STAT_NAME": "한국은행 기준금리 및 여수신금리",
        "ITEM_CODE1": "0101000",
        "ITEM_CODE2": None,
        "ITEM_NAME1": "한국은행 기준금리",
    }]
    normalized = adapter.normalize(raw)
    assert len(normalized) == 1
    assert normalized[0].value == 3.50
    assert normalized[0].observed_at == "2026-07-01"
    assert normalized[0].indicator_id == "BASE_RATE"


def test_kosis_adapter_fails_closed_without_credentials_and_parses_fixture() -> None:
    adapter = KOSISAdapter()
    assert adapter.process({}) == []

    normalized = adapter.normalize([{
        "ORG_ID": "101",
        "TBL_ID": "DT_1J22003",
        "ITM_ID": "T",
        "C1_NM": "전국",
        "PRD_SE": "M",
        "UNIT_NM": "2020=100",
        "PRD_DE": "202607",
        "DT": "115.2",
        "LST_CHN_DE": "20260804",
    }])
    assert len(normalized) == 1
    assert normalized[0].value == 115.2
    assert normalized[0].indicator_id == "CONSUMER_PRICE_INDEX"


def test_customs_adapter_fails_closed_without_credentials_and_parses_fixture() -> None:
    adapter = CustomsAdapter()
    assert adapter.process({}) == []

    normalized = adapter.normalize([{
        "hsCode": "0901110000",
        "impDlr": "1500.50",
        "impWgt": "100",
        "year": "2026.07",
    }])
    assert len(normalized) == 3
    assert next(item.value for item in normalized if item.unit == "USD") == 1500.50
    assert next(item.value for item in normalized if item.unit == "USD_PER_KG") == 15.005
    assert all("IMPORT_PRICE" not in item.indicator_id for item in normalized)


def test_public_data_adapter_fails_closed_without_credentials() -> None:
    assert PublicDataStoreAdapter().process({}) == []


def test_map_adapter_fails_closed_without_credentials() -> None:
    latitude, longitude, metadata = MapApiAdapter().geocode_address(
        "서울특별시 강남구 테헤란로 123"
    )
    assert latitude is None
    assert longitude is None
    assert metadata["geocode_status"] == "NOT_CONFIGURED"
