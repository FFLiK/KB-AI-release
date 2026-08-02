"""Contracts for deterministic model selection and monthly baseline forecasts."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import Field

from src.contracts.research import StrictModel


class ForecastStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED = "FAILED"


class IntervalKind(str, Enum):
    PREDICTION_INTERVAL = "PREDICTION_INTERVAL"
    ASSUMPTION_RANGE = "ASSUMPTION_RANGE"
    NONE = "NONE"


class CandidateMetric(StrictModel):
    model_name: str
    model_version: str
    folds: int = Field(ge=0)
    interval_coverage: Decimal | None = Field(default=None, ge=0, le=1)
    beats_simple_baseline: bool | None = None
    mae: Decimal | None = Field(default=None, ge=0)
    smape: Decimal | None = Field(default=None, ge=0)
    directional_accuracy: Decimal | None = Field(default=None, ge=0, le=1)
    failed: bool = False
    failure_reason: str | None = None


class MonthlyForecast(StrictModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    point: Decimal = Field(ge=0)
    lower: Decimal = Field(ge=0)
    upper: Decimal = Field(ge=0)
    unit: str = "KRW"
    is_assumption_range: bool = False


class BaselineForecastBundle(StrictModel):
    forecast_id: str
    target: str = "MONTHLY_REVENUE"
    status: ForecastStatus
    selected_model: str | None = None
    model_version: str | None = None
    training_start: date | None = None
    training_end: date | None = None
    available_months: int = Field(ge=0)
    candidate_metrics: list[CandidateMetric] = Field(default_factory=list)
    fallback_reason: str | None = None
    monthly_forecasts: list[MonthlyForecast] = Field(default_factory=list)
    interval_kind: IntervalKind = IntervalKind.NONE
    assumptions: list[str] = Field(default_factory=list)
    data_snapshot_ids: list[str] = Field(default_factory=list)
    version: str = "baseline_forecast_bundle.v1"
