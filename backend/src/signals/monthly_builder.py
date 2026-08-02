"""Build month-aligned scenario adjustments from accepted evidence-backed events."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date

from src.contracts.canonical_event import CanonicalEvent
from src.contracts.scenario import MonthlyScenarioAdjustment, ScenarioAdjustmentV2
from src.contracts.store import StoreProfile
from src.contracts.store_signal import StoreSignal
from src.signals.research_signal import ResearchSignalBuilder


def _month_add(start: date, offset: int) -> str:
    index = start.year * 12 + start.month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


class MonthlySignalBuilder:
    def __init__(self, legacy_builder: ResearchSignalBuilder | None = None):
        self.legacy_builder = legacy_builder or ResearchSignalBuilder()

    def build(
        self,
        events: list[CanonicalEvent],
        store: StoreProfile,
        forecast_start: date,
        months: int,
    ) -> tuple[list[StoreSignal], dict[str, ScenarioAdjustmentV2]]:
        signals, _ = self.legacy_builder.build(events, store, forecast_start, months)
        grouped: dict[str, list[StoreSignal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.month].append(signal)
        month_names = [_month_add(forecast_start, offset) for offset in range(months)]
        results: dict[str, ScenarioAdjustmentV2] = {}
        for scenario in ("BASELINE", "LOW_IMPACT", "HIGH_IMPACT"):
            month_adjustments = []
            source_ids: set[str] = set()
            for month in month_names:
                month_signals = grouped.get(month, [])
                legacy = self.legacy_builder._adjust(scenario, month_signals)
                source_ids.update(legacy.source_ids)
                month_adjustments.append(MonthlyScenarioAdjustment(
                    month=month,
                    revenue_multiplier=legacy.revenue_multiplier,
                    variable_cost_multiplier=legacy.variable_cost_multiplier,
                    fixed_cost_multiplier=legacy.fixed_cost_multiplier,
                    interest_rate_delta=legacy.interest_rate_delta,
                    event_ids=legacy.event_ids,
                    signal_ids=legacy.signal_ids,
                    coefficient_ids=sorted({signal.coefficient_id for signal in month_signals}),
                ))
            identity = f"{scenario}|{'|'.join(month_names)}|{'|'.join(sorted(signal.signal_id for signal in signals))}"
            results[scenario] = ScenarioAdjustmentV2(
                adjustment_id="ADJ-" + hashlib.sha256(identity.encode()).hexdigest()[:20].upper(),
                scenario=scenario,
                months=month_adjustments,
                source_ids=sorted(source_ids),
            )
        return signals, results
