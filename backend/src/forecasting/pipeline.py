"""Backtested baseline forecasting with deterministic candidate selection."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from src.contracts.forecast import (
    BaselineForecastBundle,
    CandidateMetric,
    ForecastStatus,
    IntervalKind,
    MonthlyForecast,
)
from src.contracts.store import MonthlyHistory, StoreProfile
from src.contracts.official import OfficialFeatureSet
from src.storage.analysis_repository import ForecastRepository


def _month_add(month: str, offset: int) -> str:
    year, number = (int(part) for part in month.split("-"))
    index = year * 12 + number - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


class ForecastModel(Protocol):
    name: str
    version: str
    min_history: int

    def predict(self, values: list[Decimal], horizon: int) -> list[Decimal]: ...


@dataclass(frozen=True)
class RecentMeanModel:
    name: str = "RECENT_MEAN"
    version: str = "recent_mean.v1"
    min_history: int = 2

    def predict(self, values: list[Decimal], horizon: int) -> list[Decimal]:
        window = values[-min(6, len(values)):]
        point = sum(window) / Decimal(len(window))
        return [max(Decimal("0"), point)] * horizon


@dataclass(frozen=True)
class RecentTrendModel:
    name: str = "RECENT_TREND"
    version: str = "recent_trend.v1"
    min_history: int = 4

    def predict(self, values: list[Decimal], horizon: int) -> list[Decimal]:
        window = values[-min(6, len(values)):]
        slopes = [window[index] - window[index - 1] for index in range(1, len(window))]
        slope = sum(slopes) / Decimal(len(slopes))
        return [max(Decimal("0"), window[-1] + slope * Decimal(step)) for step in range(1, horizon + 1)]


@dataclass(frozen=True)
class DampedTrendModel:
    name: str = "DAMPED_TREND"
    version: str = "damped_trend.v1"
    min_history: int = 8
    damping: Decimal = Decimal("0.8")

    def predict(self, values: list[Decimal], horizon: int) -> list[Decimal]:
        window = values[-min(12, len(values)):]
        slope = (window[-1] - window[0]) / Decimal(max(1, len(window) - 1))
        cumulative = Decimal("0")
        output = []
        for step in range(1, horizon + 1):
            cumulative += self.damping ** step
            output.append(max(Decimal("0"), window[-1] + slope * cumulative))
        return output


@dataclass(frozen=True)
class SeasonalNaiveModel:
    name: str = "SEASONAL_NAIVE"
    version: str = "seasonal_naive.v1"
    min_history: int = 12

    def predict(self, values: list[Decimal], horizon: int) -> list[Decimal]:
        season = values[-12:]
        return [max(Decimal("0"), season[index % 12]) for index in range(horizon)]


@dataclass(frozen=True)
class ETSModel:
    name: str = "ETS_DAMPED"
    version: str = "ets_damped.v1"
    min_history: int = 18

    def predict(self, values: list[Decimal], horizon: int) -> list[Decimal]:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        fitted = ExponentialSmoothing(
            [float(value) for value in values], trend="add", damped_trend=True,
            seasonal="add" if len(values) >= 24 else None,
            seasonal_periods=12 if len(values) >= 24 else None,
            initialization_method="estimated",
        ).fit(optimized=True, remove_bias=False)
        return [max(Decimal("0"), Decimal(str(value))) for value in fitted.forecast(horizon)]


@dataclass(frozen=True)
class SARIMAModel:
    name: str = "SARIMA"
    version: str = "sarima_101_011.v1"
    min_history: int = 24

    def predict(self, values: list[Decimal], horizon: int) -> list[Decimal]:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        fitted = SARIMAX(
            [float(value) for value in values], order=(1, 0, 1), seasonal_order=(0, 1, 1, 12),
            enforce_stationarity=False, enforce_invertibility=False,
        ).fit(disp=False, maxiter=50)
        return [max(Decimal("0"), Decimal(str(value))) for value in fitted.forecast(horizon)]


MODEL_PRIORITY = {
    "SEASONAL_NAIVE": 0,
    "DAMPED_TREND": 1,
    "RECENT_MEAN": 2,
    "RECENT_TREND": 3,
    "ETS_DAMPED": 4,
    "SARIMA": 5,
}


def _metric(model: ForecastModel, values: list[Decimal], backtest_windows: int = 12) -> CandidateMetric:
    start = max(model.min_history, 4, len(values) - max(1, backtest_windows))
    predictions: list[Decimal] = []
    actuals: list[Decimal] = []
    direction_hits = 0
    direction_total = 0
    for split in range(start, len(values)):
        predicted = model.predict(values[:split], 1)[0]
        actual = values[split]
        predictions.append(predicted)
        actuals.append(actual)
        if split >= 1:
            predicted_direction = (predicted > values[split - 1]) - (predicted < values[split - 1])
            actual_direction = (actual > values[split - 1]) - (actual < values[split - 1])
            direction_hits += int(predicted_direction == actual_direction)
            direction_total += 1
    if not actuals:
        return CandidateMetric(model_name=model.name, model_version=model.version, folds=0)
    mae = sum(abs(actual - predicted) for actual, predicted in zip(actuals, predictions)) / Decimal(len(actuals))
    smape_terms = []
    for actual, predicted in zip(actuals, predictions):
        denominator = abs(actual) + abs(predicted)
        smape_terms.append(Decimal("0") if denominator == 0 else Decimal("2") * abs(actual - predicted) / denominator)
    smape = sum(smape_terms) / Decimal(len(smape_terms))
    directional = Decimal(direction_hits) / Decimal(direction_total) if direction_total else Decimal("0")
    interval_width = mae * Decimal("1.96")
    coverage = Decimal(sum(1 for actual, predicted in zip(actuals, predictions) if abs(actual - predicted) <= interval_width)) / Decimal(len(actuals))
    return CandidateMetric(
        model_name=model.name, model_version=model.version, folds=len(actuals),
        mae=mae, smape=smape, directional_accuracy=directional, interval_coverage=coverage,
    )


class BaselineForecastPipeline:
    def __init__(self, repository: ForecastRepository | None = None, min_improvement: Decimal = Decimal("0"), backtest_windows: int = 12):
        self.repository = repository
        self.min_improvement = min_improvement
        self.backtest_windows = max(1, backtest_windows)

    def run(
        self,
        run_id: str,
        store: StoreProfile,
        forecast_start: date,
        data_snapshot_ids: list[str] | None = None,
        official_features: OfficialFeatureSet | None = None,
    ) -> BaselineForecastBundle:
        ordered = sorted(store.monthly_history, key=lambda item: item.month)
        values = [item.revenue_krw for item in ordered]
        available = len(values)
        snapshot_ids = sorted(data_snapshot_ids or [])
        identity = f"{run_id}|{forecast_start}|{available}|{'|'.join(str(value) for value in values)}|{'|'.join(snapshot_ids)}|{official_features.feature_set_id if official_features else 'NO_FEATURES'}"
        forecast_id = "FRC-" + hashlib.sha256(identity.encode()).hexdigest()[:24].upper()
        if available == 0 and store.declared_monthly_revenue_krw is None:
            bundle = BaselineForecastBundle(
                forecast_id=forecast_id, status=ForecastStatus.INSUFFICIENT_DATA,
                available_months=0, fallback_reason="No history or declared baseline revenue",
                assumptions=["Financial calculation is disabled until a revenue baseline is supplied"],
                data_snapshot_ids=snapshot_ids,
            )
            if self.repository:
                self.repository.save(run_id, bundle)
            return bundle

        if available < 6:
            point = store.declared_monthly_revenue_krw or values[-1]
            forecasts = [point] * store.forecast_horizon_months
            metrics: list[CandidateMetric] = []
            selected_name = "DECLARED_BASELINE" if store.declared_monthly_revenue_krw is not None else "LAST_OBSERVED_ASSUMPTION"
            selected_version = "assumption_range.v1"
            interval_kind = IntervalKind.ASSUMPTION_RANGE
            fallback = f"Only {available} historical months are available"
            residual_width = point * Decimal("0.20")
        else:
            candidates: list[ForecastModel]
            if available < 12:
                candidates = [RecentMeanModel(), RecentTrendModel()]
            elif available < 24:
                candidates = [RecentMeanModel(), SeasonalNaiveModel(), DampedTrendModel()]
            else:
                candidates = [RecentMeanModel(), SeasonalNaiveModel(), ETSModel(), SARIMAModel()]
            successful: list[tuple[ForecastModel, CandidateMetric]] = []
            metrics = []
            for model in candidates:
                try:
                    metric = _metric(model, values, self.backtest_windows)
                    metrics.append(metric)
                    successful.append((model, metric))
                except Exception as exc:
                    metrics.append(CandidateMetric(
                        model_name=model.name, model_version=model.version, folds=0,
                        failed=True, failure_reason=f"{type(exc).__name__}: {exc}",
                    ))
            if not successful:
                fallback_model = RecentMeanModel()
                forecasts = fallback_model.predict(values, store.forecast_horizon_months)
                selected_name, selected_version = fallback_model.name, fallback_model.version
                fallback = "All preferred models failed; recent mean selected"
                residual_width = forecasts[0] * Decimal("0.20") if forecasts else Decimal("0")
                interval_kind = IntervalKind.ASSUMPTION_RANGE
            else:
                ranked = sorted(successful, key=lambda item: (
                    item[1].smape if item[1].smape is not None else Decimal("Infinity"),
                    item[1].mae if item[1].mae is not None else Decimal("Infinity"),
                    MODEL_PRIORITY[item[0].name],
                ))
                selected_model, selected_metric = ranked[0]
                simple = next((item for item in successful if item[0].name == "RECENT_MEAN"), None)
                fallback = None
                if simple and selected_model.name != "RECENT_MEAN" and simple[1].smape is not None:
                    threshold = simple[1].smape * (Decimal("1") - self.min_improvement)
                    if selected_metric.smape is None or selected_metric.smape > threshold:
                        selected_model, selected_metric = simple
                        fallback = "Preferred model did not meet the required improvement over RECENT_MEAN"
                if simple and simple[1].smape is not None:
                    threshold = simple[1].smape * (Decimal("1") - self.min_improvement)
                    for _, metric in successful:
                        metric.beats_simple_baseline = metric.smape is not None and metric.smape <= threshold
                forecasts = selected_model.predict(values, store.forecast_horizon_months)
                selected_name, selected_version = selected_model.name, selected_model.version
                residual_width = (selected_metric.mae or Decimal("0")) * Decimal("1.96")
                if residual_width == 0:
                    residual_width = (sum(values) / Decimal(len(values))) * Decimal("0.05")
                interval_kind = IntervalKind.PREDICTION_INTERVAL
        start_month = forecast_start.strftime("%Y-%m")
        monthly = []
        for index, point in enumerate(forecasts):
            month = _month_add(start_month, index)
            feature_multiplier = (
                official_features.for_month(month).revenue_index_multiplier if official_features else Decimal("1")
            )
            adjusted_point = point * feature_multiplier
            adjusted_width = residual_width * feature_multiplier
            monthly.append(MonthlyForecast(
                month=month,
                point=adjusted_point,
                lower=max(Decimal("0"), adjusted_point - adjusted_width),
                upper=adjusted_point + adjusted_width,
                is_assumption_range=interval_kind == IntervalKind.ASSUMPTION_RANGE,
            ))
        bundle = BaselineForecastBundle(
            forecast_id=forecast_id,
            status=ForecastStatus.PARTIAL if interval_kind == IntervalKind.ASSUMPTION_RANGE else ForecastStatus.COMPLETED,
            selected_model=selected_name,
            model_version=selected_version,
            training_start=date.fromisoformat(ordered[0].month + "-01") if ordered else None,
            training_end=date.fromisoformat(ordered[-1].month + "-01") if ordered else None,
            available_months=available,
            candidate_metrics=metrics,
            fallback_reason=fallback,
            monthly_forecasts=monthly,
            interval_kind=interval_kind,
            assumptions=[
                "Intervals are empirical error bands, not guarantees",
                *(["Validated official feature multipliers were applied"] if official_features else []),
            ],
            data_snapshot_ids=snapshot_ids,
        )
        if self.repository:
            self.repository.save(run_id, bundle)
        return bundle
