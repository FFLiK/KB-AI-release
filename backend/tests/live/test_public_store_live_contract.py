from datetime import UTC, datetime

import pytest

from src.config.credential_validation import get_credential
from src.ingestion.official_api.public_data import PublicDataStoreAdapter


pytestmark = pytest.mark.live


def test_public_store_one_live_snapshot_contract() -> None:
    if not (get_credential("PUBLIC_DATA_API_KEY") or get_credential("DATA_GO_KR_API_KEY")):
        pytest.skip("Public Data Portal credential is not configured")
    adapter = PublicDataStoreAdapter()
    nearby = adapter.process({
        "endpoint": "storeListInRadius",
        "radius": 50,
        "cx": 127.0365,
        "cy": 37.5007,
        "numOfRows": 1,
        "pageNo": 1,
    })
    assert adapter.last_error_code is None
    assert nearby

    snapshot = adapter.build_snapshot(
        {"endpoint": "storeOne", "key": nearby[0].business_id},
        datetime.now(UTC),
    )

    assert adapter.last_error_code is None
    assert snapshot is not None and len(snapshot.records) == 1
    assert snapshot.records[0].business_id == nearby[0].business_id
    assert snapshot.provider_reference_month.isdigit()
    assert snapshot.body_hash and snapshot.source_revision_id
