from datetime import date

from src.forecasting.official_features import OfficialFeatureBuilder
from src.orchestration.official_data_pipeline import FakeOfficialAdapter, OfficialDataPipeline
from tests.e2e.support import load_official_observations, official_requests


def test_future_and_missing_release_observations_are_rejected() -> None:
    records = [item for item in load_official_observations() if item["indicator_id"] == "USD_KRW"]
    records.extend([
        {
            **records[-1],
            "observed_at": "2026-08-01",
            "released_at": "2026-08-10T09:00:00+09:00",
            "available_at": "2026-08-10T09:00:00+09:00",
            "value": "9999",
        },
        {
            **records[-1],
            "observed_at": "2026-07-01",
            "released_at": None,
            "available_at": None,
            "value": "8888",
        },
    ])
    pipeline = OfficialDataPipeline({"REPLAY": FakeOfficialAdapter(records)})

    bundle = pipeline.run(
        "AS-OF-CONTRACT",
        date(2026, 7, 31),
        official_requests(("USD_KRW",)),
    )

    assert [item.value for item in bundle.observations] == [1300, 1326]
    assert "NOT_AVAILABLE_AS_OF_ANALYSIS_DATE" in bundle.provider_errors.values()
    assert "MISSING_RELEASE_METADATA" in bundle.provider_errors.values()


def test_stale_observations_remain_traceable_but_do_not_create_features() -> None:
    records = [item for item in load_official_observations() if item["indicator_id"] == "USD_KRW"]
    for item in records:
        item["observed_at"] = "2026-03-01" if item["value"] == "1300" else "2026-04-01"
        item["released_at"] = "2026-04-10T09:00:00+09:00"
        item["available_at"] = "2026-04-11T09:00:00+09:00"
    request = official_requests(("USD_KRW",))[0].model_copy(update={"max_age_days": 30})
    bundle = OfficialDataPipeline({"REPLAY": FakeOfficialAdapter(records)}).run(
        "STALE-CONTRACT",
        date(2026, 7, 31),
        [request],
    )
    features = OfficialFeatureBuilder().build(bundle, date(2026, 8, 1), 2)

    assert len(bundle.observations) == 2
    assert all(item.quality_status == "STALE" for item in bundle.observations)
    assert features.indicator_ids == []
    assert all(item.ingredient_cost_multiplier == 1 for item in features.months)
