"""Deterministic CSV row validation for the versioned store-history template."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field


MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
SUPPORTED_SCHEMA_VERSION = "store_history.v1"


class CSVValidationErrorDetail(BaseModel):
    step: str
    column: str
    message: str


class ParseResult(BaseModel):
    is_valid: bool
    data: dict[str, Any] | None = None
    errors: list[CSVValidationErrorDetail] = Field(default_factory=list)
    warnings: list[CSVValidationErrorDetail] = Field(default_factory=list)


def _decimal(
    row: dict[str, Any],
    column: str,
    row_index: int,
    errors: list[CSVValidationErrorDetail],
    required: bool,
) -> Decimal | None:
    raw = row.get(column)
    if raw is None or str(raw).strip() == "":
        if required:
            errors.append(CSVValidationErrorDetail(
                step="REQUIRED_VALUE", column=column, message=f"Row {row_index}: {column} is missing"
            ))
        return None
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        errors.append(CSVValidationErrorDetail(
            step="DATA_TYPE", column=column, message=f"Row {row_index}: invalid decimal format"
        ))
        return None
    if not value.is_finite() or value < 0:
        errors.append(CSVValidationErrorDetail(
            step="RANGE_CHECK", column=column, message=f"Row {row_index}: {column} must be finite and >= 0"
        ))
        return None
    return value


def _month_index(value: str) -> int:
    year, month = (int(part) for part in value.split("-"))
    return year * 12 + month - 1


def parse_and_validate_csv_input(raw_rows: list[dict[str, Any]]) -> ParseResult:
    errors: list[CSVValidationErrorDetail] = []
    warnings: list[CSVValidationErrorDetail] = []
    if not raw_rows:
        return ParseResult(is_valid=False, errors=[CSVValidationErrorDetail(
            step="FILE_FORMAT", column="ALL", message="CSV file is empty"
        )])

    required_columns = ["month", "revenue_krw", "variable_costs_krw", "fixed_costs_krw"]
    headers = set(raw_rows[0])
    for column in required_columns:
        if column not in headers:
            errors.append(CSVValidationErrorDetail(
                step="SCHEMA_HEADER", column=column, message=f"Missing required header: {column}"
            ))
    if errors:
        return ParseResult(is_valid=False, errors=errors)

    versions = {str(row.get("schema_version", "")).strip() for row in raw_rows if row.get("schema_version")}
    if not versions:
        warnings.append(CSVValidationErrorDetail(
            step="SCHEMA_VERSION", column="schema_version",
            message="Legacy compatibility mode: schema_version was not supplied",
        ))
    elif versions != {SUPPORTED_SCHEMA_VERSION}:
        errors.append(CSVValidationErrorDetail(
            step="SCHEMA_VERSION", column="schema_version",
            message=f"Only {SUPPORTED_SCHEMA_VERSION} is supported",
        ))

    parsed_history: list[dict[str, Any]] = []
    months_seen: set[str] = set()
    for index, row in enumerate(raw_rows):
        month = str(row.get("month", "")).strip()
        if not MONTH_PATTERN.fullmatch(month):
            errors.append(CSVValidationErrorDetail(
                step="DATA_TYPE", column="month", message=f"Row {index}: month must be YYYY-MM"
            ))
            continue
        if month in months_seen:
            errors.append(CSVValidationErrorDetail(
                step="TIMESERIES_CONTINUITY", column="month", message=f"Duplicate month entry: {month}"
            ))
        months_seen.add(month)

        revenue = _decimal(row, "revenue_krw", index, errors, True)
        variable_total = _decimal(row, "variable_costs_krw", index, errors, True)
        fixed_total = _decimal(row, "fixed_costs_krw", index, errors, True)
        variable_columns = ["ingredients_krw", "platform_fee_krw", "payment_fee_krw"]
        fixed_columns = ["rent_krw", "labor_krw", "utilities_krw", "other_fixed_krw"]
        variable_parts = {name: _decimal(row, name, index, errors, False) for name in variable_columns}
        fixed_parts = {name: _decimal(row, name, index, errors, False) for name in fixed_columns}

        if all(value is not None for value in variable_parts.values()) and variable_total is not None:
            detail_sum = sum(variable_parts.values(), Decimal("0"))
            if abs(detail_sum - variable_total) > Decimal("1"):
                errors.append(CSVValidationErrorDetail(
                    step="ACCOUNTING_SUM", column="variable_costs_krw",
                    message=f"Row {index}: variable detail sum {detail_sum} differs from total {variable_total}",
                ))
        elif any(value is not None for value in variable_parts.values()):
            errors.append(CSVValidationErrorDetail(
                step="ACCOUNTING_SUM", column="variable_cost_details",
                message=f"Row {index}: partial variable-cost details cannot be reconciled",
            ))
        else:
            warnings.append(CSVValidationErrorDetail(
                step="MISSING_OPTIONAL_DETAIL", column="variable_cost_details",
                message=f"Row {index}: missing variable-cost details remain unknown",
            ))
        if all(value is not None for value in fixed_parts.values()) and fixed_total is not None:
            detail_sum = sum(fixed_parts.values(), Decimal("0"))
            if abs(detail_sum - fixed_total) > Decimal("1"):
                errors.append(CSVValidationErrorDetail(
                    step="ACCOUNTING_SUM", column="fixed_costs_krw",
                    message=f"Row {index}: fixed detail sum {detail_sum} differs from total {fixed_total}",
                ))

        if row.get("annual_interest_rate") not in (None, ""):
            rate = _decimal(row, "annual_interest_rate", index, errors, True)
            rate_unit = str(row.get("interest_rate_unit", "")).upper()
            if rate_unit not in {"DECIMAL", "PERCENT"}:
                errors.append(CSVValidationErrorDetail(
                    step="UNIT", column="interest_rate_unit",
                    message=f"Row {index}: interest_rate_unit must be DECIMAL or PERCENT",
                ))
            elif rate is not None and rate_unit == "DECIMAL" and rate > 1:
                errors.append(CSVValidationErrorDetail(
                    step="RANGE_CHECK", column="annual_interest_rate",
                    message=f"Row {index}: decimal interest rate must be between 0 and 1",
                ))

        parsed_history.append({
            "month": month,
            "revenue_krw": revenue,
            "variable_costs_krw": variable_total,
            "fixed_costs_krw": fixed_total,
            "variable_cost_details": variable_parts,
            "fixed_cost_details": fixed_parts,
        })

    ordered_months = sorted(months_seen, key=_month_index)
    for previous, current in zip(ordered_months, ordered_months[1:]):
        if _month_index(current) != _month_index(previous) + 1:
            errors.append(CSVValidationErrorDetail(
                step="TIMESERIES_CONTINUITY", column="month",
                message=f"Missing month between {previous} and {current}; values were not interpolated",
            ))

    if errors:
        return ParseResult(is_valid=False, errors=errors, warnings=warnings)
    return ParseResult(
        is_valid=True,
        data={"schema_version": SUPPORTED_SCHEMA_VERSION, "monthly_history": parsed_history},
        warnings=warnings,
    )
