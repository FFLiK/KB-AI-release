from datetime import date
from decimal import Decimal

from src.contracts.official import OfficialDataRequest
from src.forecasting.official_features import OfficialFeatureBuilder
from src.orchestration.official_data_pipeline import FakeOfficialAdapter, OfficialDataPipeline


def bundle_for(indicator_id: str, provider: str, previous: str, latest: str, unit: str):
    records = [
        {
            "indicator_id": indicator_id,
            "value": value,
            "unit": unit,
            "frequency": "MONTHLY",
            "observed_at": observed_at,
            "released_at": released_at,
            "source_id": f"SRC-{indicator_id}",
            "source_revision_id": f"REV-{observed_at}",
        }
        for value, observed_at, released_at in (
            (previous, "2026-05-01", "2026-06-10T09:00:00+09:00"),
            (latest, "2026-06-01", "2026-07-10T09:00:00+09:00"),
        )
    ]
    return OfficialDataPipeline({provider: FakeOfficialAdapter(records)}).run(
        f"RUN-{indicator_id}",
        date(2026, 7, 31),
        [OfficialDataRequest(provider=provider, indicator_id=indicator_id)],
    )


def test_import_price_shock_decays_and_never_reaches_old_unstable_path() -> None:
    bundle = bundle_for(
        "IMPORT_PRICE_INDEX_USD", "ECOS", "133.57", "124.58", "INDEX_2020_100"
    )
    features = OfficialFeatureBuilder().build(bundle, date(2026, 8, 1), 6)
    values = [month.indicator_values["IMPORT_PRICE_INDEX_USD"] for month in features.months]
    assert values[-1] >= Decimal("124.58") * Decimal("0.88")
    assert values[-1] > Decimal("100")
    assert values[-1] < values[0]
    contribution = features.months[-1].contributions[0]
    assert contribution.decay_factor == Decimal("0.65")
    assert abs(contribution.cumulative_relative_change) <= Decimal("0.12")
    assert features.transformation_version == "official_features.v2.decayed_capped"


def test_positive_fx_change_has_positive_bounded_imported_cost_effect() -> None:
    bundle = bundle_for("USD_KRW", "ECOS", "1490.11", "1527.30", "KRW_PER_USD")
    features = OfficialFeatureBuilder().build(bundle, date(2026, 8, 1), 12)
    multipliers = [month.imported_ingredient_cost_multiplier for month in features.months]
    assert all(Decimal("1") <= item <= Decimal("1.12") for item in multipliers)
    assert multipliers[-1] >= multipliers[0]


def test_missing_observations_are_not_imputed() -> None:
    bundle = OfficialDataPipeline({"CUSTOMS": FakeOfficialAdapter([])}).run(
        "RUN-MISSING-CUSTOMS",
        date(2026, 7, 31),
        [OfficialDataRequest(
            provider="CUSTOMS",
            indicator_id="CUSTOMS_IMPORT_UNIT_PRICE_USD_PER_KG_HS0901110000",
        )],
    )
    features = OfficialFeatureBuilder().build(bundle, date(2026, 8, 1), 3)
    assert features.indicator_ids == []
    assert all(month.indicator_values == {} for month in features.months)
    assert all(month.ingredient_cost_multiplier == Decimal("1") for month in features.months)


def test_indicator_roles_do_not_leak_into_unrelated_feature_groups() -> None:
    cpi = bundle_for("CONSUMER_PRICE_INDEX", "KOSIS", "100", "105", "INDEX_2020_100")
    month = OfficialFeatureBuilder().build(cpi, date(2026, 8, 1), 1).months[0]
    assert month.domestic_ingredient_cost_multiplier > Decimal("1")
    assert month.imported_ingredient_cost_multiplier == Decimal("1")
    assert month.revenue_index_multiplier == Decimal("1")
    assert month.interest_rate_delta == Decimal("0")
