import json
from decimal import Decimal
from pathlib import Path

from src.contracts.store import StoreProfile
from scripts.generate_sample_store_fixtures import generate_fixtures


FIXTURE_DIR = Path("tests/fixtures/stores")


def _load(name: str) -> StoreProfile:
    return StoreProfile.model_validate_json((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_fixture_generator_reproduces_committed_content(tmp_path: Path) -> None:
    generated = generate_fixtures(tmp_path)

    assert {path.name for path in generated} == {path.name for path in FIXTURE_DIR.glob("*.json")}
    for path in generated:
        assert path.read_bytes() == (FIXTURE_DIR / path.name).read_bytes()


def test_primary_cafe_fixture_has_exact_transparent_history() -> None:
    store = _load("cafe_gangnam_24m.json")

    assert len(store.monthly_history) == 24
    assert [item.month for item in store.monthly_history] == [
        f"{(2024 * 12 + 7 + offset) // 12:04d}-{(2024 * 12 + 7 + offset) % 12 + 1:02d}"
        for offset in range(24)
    ]
    assert store.monthly_history[0].revenue_krw == 29_000_000
    assert store.monthly_history[4].month == "2024-12"
    assert store.monthly_history[4].revenue_krw == 31_968_000
    assert store.monthly_history[-1].fixed_costs.labor_krw == 7_900_000
    assert store.monthly_history[-1].transaction_count == int(
        store.monthly_history[-1].revenue_krw // 8_500
    )
    assert store.loans[0].rate_type == "VARIABLE"
    assert store.cost_exposures.imported_ingredient_share == Decimal("0.45")


def test_control_and_boundary_fixtures_encode_acceptance_conditions() -> None:
    domestic = _load("restaurant_domestic_12m.json")
    new_store = _load("new_store_3m.json")
    invalid = _load("invalid_address_store.json")

    assert len(domestic.monthly_history) == 12
    assert domestic.cost_exposures.imported_ingredient_share == 0
    assert all(loan.rate_type == "FIXED" for loan in domestic.loans)
    assert len(new_store.monthly_history) == 3
    assert invalid.latitude is None and invalid.longitude is None
    assert "가상특별시" in invalid.address
