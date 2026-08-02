"""Monthly scenario adjustment contracts."""
from __future__ import annotations

import hashlib
from decimal import Decimal

from pydantic import Field

from src.contracts.research import StrictModel
from src.contracts.store_signal import ScenarioAdjustment


class MonthlyScenarioAdjustment(StrictModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    revenue_multiplier: Decimal = Decimal("1")
    variable_cost_multiplier: Decimal = Decimal("1")
    fixed_cost_multiplier: Decimal = Decimal("1")
    interest_rate_delta: Decimal = Decimal("0")
    event_ids: list[str] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    coefficient_ids: list[str] = Field(default_factory=list)


class ScenarioAdjustmentV2(StrictModel):
    adjustment_id: str
    scenario: str
    months: list[MonthlyScenarioAdjustment] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    coefficient_version: str = "coefficients.v1"

    @classmethod
    def from_legacy(cls, adjustment: ScenarioAdjustment, months: list[str]) -> "ScenarioAdjustmentV2":
        payload = f"{adjustment.scenario}|{'|'.join(months)}|{'|'.join(sorted(adjustment.signal_ids))}"
        adjustment_id = "ADJ-" + hashlib.sha256(payload.encode()).hexdigest()[:20].upper()
        monthly = []
        for month in months:
            month_signal_ids = [signal_id for signal_id in adjustment.signal_ids]
            monthly.append(MonthlyScenarioAdjustment(
                month=month,
                revenue_multiplier=adjustment.revenue_multiplier,
                variable_cost_multiplier=adjustment.variable_cost_multiplier,
                fixed_cost_multiplier=adjustment.fixed_cost_multiplier,
                interest_rate_delta=adjustment.interest_rate_delta,
                event_ids=adjustment.event_ids,
                signal_ids=month_signal_ids,
            ))
        return cls(
            adjustment_id=adjustment_id,
            scenario=adjustment.scenario,
            months=monthly,
            source_ids=adjustment.source_ids,
            coefficient_version=adjustment.coefficient_version,
        )
