"""Generate deterministic, fictional store fixtures used by offline E2E tests."""

from __future__ import annotations

import argparse
import json
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any


def _month_add(month: str, offset: int) -> str:
    year, number = (int(part) for part in month.split("-"))
    index = year * 12 + number - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _money(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def _history(start_month: str, months: int, base_revenue: int = 29_000_000) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index in range(months):
        month = _month_add(start_month, index)
        month_number = int(month[-2:])
        revenue = Decimal(base_revenue + 150_000 * index)
        if month_number == 12:
            revenue *= Decimal("1.08")
        elif month_number in {1, 2}:
            revenue *= Decimal("0.93")
        revenue_krw = _money(revenue)
        labor_krw = 7_900_000 if index >= months - 6 else 7_500_000
        utilities_krw = 1_035_000 if month_number in {12, 1, 2, 6, 7, 8} else 900_000
        records.append({
            "capital_expenditure_krw": 0,
            "fixed_costs": {
                "labor_krw": labor_krw,
                "other_krw": 600_000,
                "rent_krw": 4_200_000,
                "utilities_krw": utilities_krw,
            },
            "month": month,
            "revenue_krw": revenue_krw,
            "tax_cash_outflow_krw": 0,
            "transaction_count": revenue_krw // 8_500,
            "variable_costs": {
                "ingredients_krw": _money(Decimal(revenue_krw) * Decimal("0.29")),
                "payment_fee_krw": _money(Decimal(revenue_krw) * Decimal("0.021")),
                "platform_fee_krw": _money(Decimal(revenue_krw) * Decimal("0.07")),
            },
        })
    return records


def build_fixtures() -> dict[str, dict[str, Any]]:
    cafe_history = _history("2024-08", 24)
    domestic_history = _history("2025-08", 12, base_revenue=31_000_000)
    new_store_history = _history("2026-05", 3, base_revenue=18_000_000)
    invalid_address_history = _history("2025-08", 12, base_revenue=24_000_000)

    common = {
        "schema_version": "store_profile.v1",
        "opening_hours": None,
        "fixed_cost_schedule": [],
    }
    return {
        "cafe_gangnam_24m.json": {
            **common,
            "address": "서울특별시 강남구 테헤란로 152",
            "annual_revenue_krw": 372_000_000,
            "business_start_date": "2023-01-01",
            "business_type_code": "FNB_CAFE",
            "cost_exposures": {
                "imported_ingredient_share": 0.45,
                "variable_rate_debt_share": 0.70,
            },
            "current_cash_krw": 15_000_000,
            "employee_count": 4,
            "forecast_horizon_months": 6,
            "latitude": None,
            "loans": [{
                "annual_interest_rate": 0.063,
                "loan_id": "LOAN-SAMPLE-001",
                "principal_balance_krw": 80_000_000,
                "rate_type": "VARIABLE",
                "remaining_months": 24,
                "repayment_type": "BULLET",
            }],
            "longitude": None,
            "minimum_operating_cash_krw": 6_000_000,
            "monthly_history": cafe_history,
            "store_id": "STORE-SAMPLE-CAFE-GANGNAM",
        },
        "restaurant_domestic_12m.json": {
            **common,
            "address": "서울특별시 종로구 종로 1",
            "annual_revenue_krw": 390_000_000,
            "business_start_date": "2022-03-01",
            "business_type_code": "FNB_RESTAURANT",
            "cost_exposures": {
                "imported_ingredient_share": 0,
                "variable_rate_debt_share": 0,
            },
            "current_cash_krw": 18_000_000,
            "employee_count": 5,
            "forecast_horizon_months": 6,
            "latitude": 37.5700,
            "loans": [{
                "annual_interest_rate": 0.052,
                "loan_id": "LOAN-SAMPLE-FIXED-001",
                "principal_balance_krw": 50_000_000,
                "rate_type": "FIXED",
                "remaining_months": 36,
                "repayment_type": "BULLET",
            }],
            "longitude": 126.9769,
            "minimum_operating_cash_krw": 7_000_000,
            "monthly_history": domestic_history,
            "store_id": "STORE-SAMPLE-RESTAURANT-DOMESTIC",
        },
        "new_store_3m.json": {
            **common,
            "address": "서울특별시 마포구 월드컵북로 10",
            "annual_revenue_krw": None,
            "business_start_date": "2026-05-01",
            "business_type_code": "FNB_CAFE",
            "cost_exposures": {
                "imported_ingredient_share": 0.20,
                "variable_rate_debt_share": 0,
            },
            "current_cash_krw": 9_000_000,
            "employee_count": 2,
            "forecast_horizon_months": 6,
            "latitude": 37.5664,
            "loans": [],
            "longitude": 126.9019,
            "minimum_operating_cash_krw": 4_000_000,
            "monthly_history": new_store_history,
            "store_id": "STORE-SAMPLE-NEW-3M",
        },
        "invalid_address_store.json": {
            **common,
            "address": "가상특별시 존재하지않는구 허구로 99999",
            "annual_revenue_krw": 300_000_000,
            "business_start_date": "2024-01-01",
            "business_type_code": "FNB_RESTAURANT",
            "cost_exposures": {
                "imported_ingredient_share": 0.10,
                "variable_rate_debt_share": 0,
            },
            "current_cash_krw": 12_000_000,
            "employee_count": 3,
            "forecast_horizon_months": 6,
            "latitude": None,
            "loans": [],
            "longitude": None,
            "minimum_operating_cash_krw": 5_000_000,
            "monthly_history": invalid_address_history,
            "store_id": "STORE-SAMPLE-INVALID-ADDRESS",
        },
    }


def generate_fixtures(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, payload in sorted(build_fixtures().items()):
        path = output_dir / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/fixtures/stores"),
    )
    args = parser.parse_args()
    generate_fixtures(args.output_dir)


if __name__ == "__main__":
    main()
