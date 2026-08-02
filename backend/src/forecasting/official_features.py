"""Deterministic, bounded projection of official observations into model features."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date
from decimal import Decimal

from src.contracts.canonical_event import CanonicalEvent
from src.contracts.official import (
    IndicatorFeatureContribution,
    MonthlyOfficialFeatures,
    ObservationQualityStatus,
    OfficialDataBundle,
    OfficialFeatureSet,
)
from src.forecasting.official_event_bridge import apply_official_event_bridge
from src.registries.official_indicator_registry import load_official_indicator_registry

REVENUE_TOKENS = ("RETAIL", "SERVICE", "CONSUM", "SALES", "CSI", "CARD")
IMPORTED_INGREDIENT_TOKENS = ("IMPORT", "CUSTOMS", "FX", "USD_KRW")
DOMESTIC_INGREDIENT_TOKENS = ("FOOD", "INGREDIENT", "CPI", "PPI")
INTEREST_TOKENS = ("RATE", "COFIX", "CD_", "KORIBOR")
REGISTERED_INDICATORS = load_official_indicator_registry()
REGISTERED_FEATURE_ROLES = {
    indicator_id: str(definition.get("feature_role") or "")
    for indicator_id, definition in REGISTERED_INDICATORS.items()
}
DECAY = Decimal("0.65")
PER_PERIOD_RELATIVE_CAP = Decimal("0.05")
ROLE_HORIZON_CAPS = {
    "REVENUE_DEMAND": Decimal("0.10"),
    "DOMESTIC_INGREDIENT_COST": Decimal("0.08"),
    "IMPORTED_INGREDIENT_COST": Decimal("0.12"),
    "INTEREST_RATE": Decimal("0.02"),
    "UNMAPPED": Decimal("0.05"),
}


def _month_add(start: date, offset: int) -> str:
    index = start.year * 12 + start.month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _clip(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    return max(lower, min(upper, value))


def _decayed_sum(step: int) -> Decimal:
    return sum((DECAY ** index for index in range(step)), Decimal("0"))


def _role(indicator_id: str) -> str:
    configured = REGISTERED_FEATURE_ROLES.get(indicator_id, "")
    if configured:
        return configured
    normalized = indicator_id.upper()
    if any(token in normalized for token in REVENUE_TOKENS):
        return "REVENUE_DEMAND"
    if any(token in normalized for token in IMPORTED_INGREDIENT_TOKENS):
        return "IMPORTED_INGREDIENT_COST"
    if any(token in normalized for token in DOMESTIC_INGREDIENT_TOKENS):
        return "DOMESTIC_INGREDIENT_COST"
    if any(token in normalized for token in INTEREST_TOKENS):
        return "INTEREST_RATE"
    return "UNMAPPED"


def _dimension(role: str) -> str:
    return {
        "REVENUE_DEMAND": "REVENUE",
        "DOMESTIC_INGREDIENT_COST": "DOMESTIC_INGREDIENT_COST",
        "IMPORTED_INGREDIENT_COST": "IMPORTED_INGREDIENT_COST",
        "INTEREST_RATE": "INTEREST_PAYMENT",
    }.get(role, "NONE")


class OfficialFeatureBuilder:
    """Uses bounded observations plus explicitly evidenced temporary event bridges."""

    version = "official_features.v2.decayed_capped"

    def build(
        self,
        bundle: OfficialDataBundle,
        forecast_start: date,
        months: int,
        official_events: list[CanonicalEvent] | None = None,
    ) -> OfficialFeatureSet:
        bridged_bundle, event_overrides = apply_official_event_bridge(bundle, official_events)
        grouped = defaultdict(list)
        for observation in bridged_bundle.observations:
            if observation.quality_status == ObservationQualityStatus.VALID:
                grouped[observation.indicator_id].append(observation)
        for values in grouped.values():
            values.sort(key=lambda item: (item.observed_at, item.available_at, item.observation_id))

        role_counts: dict[str, int] = defaultdict(int)
        for indicator_id in grouped:
            role_counts[_role(indicator_id)] += 1

        monthly: list[MonthlyOfficialFeatures] = []
        for offset in range(months):
            step = offset + 1
            decay_sum = _decayed_sum(step)
            role_changes: dict[str, list[Decimal]] = defaultdict(list)
            interest_deltas: list[Decimal] = []
            indicator_values: dict[str, Decimal] = {}
            observation_ids: list[str] = []
            assumptions: list[str] = []
            contributions: list[IndicatorFeatureContribution] = []

            for indicator_id, observations in sorted(grouped.items()):
                latest = observations[-1]
                previous = observations[-2] if len(observations) >= 2 else None
                role = _role(indicator_id)
                dimension = _dimension(role)
                horizon_cap = ROLE_HORIZON_CAPS.get(role, Decimal("0.05"))
                level_delta = latest.value - previous.value if previous else Decimal("0")
                raw_relative_change = (
                    level_delta / abs(previous.value)
                    if previous and previous.value != 0
                    else Decimal("0")
                )
                capped_recent_change = _clip(
                    raw_relative_change,
                    -PER_PERIOD_RELATIVE_CAP,
                    PER_PERIOD_RELATIVE_CAP,
                )
                cumulative_relative_change = _clip(
                    capped_recent_change * decay_sum,
                    -horizon_cap,
                    horizon_cap,
                )
                projected_level = max(
                    Decimal("0"),
                    latest.value * (Decimal("1") + cumulative_relative_change),
                )
                contributed_delta = Decimal("0")
                if role in {
                    "REVENUE_DEMAND",
                    "DOMESTIC_INGREDIENT_COST",
                    "IMPORTED_INGREDIENT_COST",
                }:
                    role_changes[role].append(cumulative_relative_change)
                    contributed_delta = cumulative_relative_change / Decimal(role_counts[role])
                elif role == "INTEREST_RATE" and previous:
                    unit = latest.unit.upper()
                    unit_scale = (
                        Decimal("0.01")
                        if "PERCENT" in unit or unit in {"%", "PCT"}
                        else Decimal("1")
                    )
                    interest_delta = _clip(
                        level_delta * decay_sum * unit_scale,
                        -ROLE_HORIZON_CAPS["INTEREST_RATE"],
                        ROLE_HORIZON_CAPS["INTEREST_RATE"],
                    )
                    interest_deltas.append(interest_delta)
                    contributed_delta = interest_delta / Decimal(role_counts[role])
                    projected_level = max(Decimal("0"), latest.value + level_delta * decay_sum)

                indicator_values[indicator_id] = projected_level
                observation_ids.extend(item.observation_id for item in observations[-2:])
                assumptions.extend(latest.assumptions)
                definition = REGISTERED_INDICATORS.get(indicator_id, {})
                contributions.append(IndicatorFeatureContribution(
                    month=_month_add(forecast_start, offset),
                    indicator_id=indicator_id,
                    provider=str(definition.get("provider") or "UNKNOWN"),
                    feature_role=role,
                    affected_model_dimension=dimension,
                    latest_observation_id=latest.observation_id,
                    previous_observation_id=previous.observation_id if previous else None,
                    latest_value=latest.value,
                    previous_value=previous.value if previous else None,
                    unit=latest.unit,
                    latest_observed_at=latest.observed_at,
                    latest_released_at=latest.released_at,
                    absolute_change=level_delta,
                    relative_change=raw_relative_change,
                    capped_relative_change=capped_recent_change,
                    decay_factor=DECAY,
                    cumulative_relative_change=cumulative_relative_change,
                    cumulative_horizon_cap=horizon_cap,
                    projection_step=step,
                    projected_value=projected_level,
                    contributed_multiplier_delta=contributed_delta,
                    transformation_method="DECAYED_CAPPED_RECENT_CHANGE_V2",
                    assumptions=[
                        "Recent relative change is capped to +/-5% before projection",
                        "Each future incremental change decays by 0.65",
                        f"Cumulative {role} change is capped to +/-{horizon_cap}",
                        "Projected model input; not an official agency forecast",
                    ],
                    source_observation_ids=[item.observation_id for item in observations[-2:]],
                ))

            def average(role: str) -> Decimal:
                values = role_changes.get(role, [])
                return sum(values, Decimal("0")) / Decimal(len(values)) if values else Decimal("0")

            revenue_change = average("REVENUE_DEMAND")
            domestic_change = average("DOMESTIC_INGREDIENT_COST")
            imported_change = average("IMPORTED_INGREDIENT_COST")
            all_ingredient_changes = [
                *role_changes.get("DOMESTIC_INGREDIENT_COST", []),
                *role_changes.get("IMPORTED_INGREDIENT_COST", []),
            ]
            ingredient_change = (
                sum(all_ingredient_changes, Decimal("0")) / Decimal(len(all_ingredient_changes))
                if all_ingredient_changes else Decimal("0")
            )
            if grouped:
                assumptions.extend([
                    "DECAYED_CAPPED_RECENT_CHANGE_V2 applies a 0.65 decay to each future shock",
                    "Projected levels are bounded and are scenario inputs, not agency forecasts",
                ])
            else:
                assumptions.append("No valid official observations were available")
            monthly.append(MonthlyOfficialFeatures(
                month=_month_add(forecast_start, offset),
                revenue_index_multiplier=_clip(
                    Decimal("1") + revenue_change, Decimal("0.90"), Decimal("1.10")
                ),
                ingredient_cost_multiplier=_clip(
                    Decimal("1") + ingredient_change, Decimal("0.85"), Decimal("1.15")
                ),
                domestic_ingredient_cost_multiplier=_clip(
                    Decimal("1") + domestic_change, Decimal("0.92"), Decimal("1.08")
                ),
                imported_ingredient_cost_multiplier=_clip(
                    Decimal("1") + imported_change, Decimal("0.88"), Decimal("1.12")
                ),
                interest_rate_delta=(
                    sum(interest_deltas, Decimal("0")) / Decimal(len(interest_deltas))
                    if interest_deltas else Decimal("0")
                ),
                indicator_values=indicator_values,
                contributions=contributions,
                source_observation_ids=sorted(set(observation_ids)),
                assumptions=sorted(set(assumptions)),
            ))

        material = "|".join(
            [bundle.snapshot_id, forecast_start.isoformat(), str(months), self.version]
            + [item.observation_id for item in bundle.observations]
        )
        return OfficialFeatureSet(
            feature_set_id="OFS-" + hashlib.sha256(material.encode()).hexdigest()[:24].upper(),
            as_of_date=bundle.as_of_date,
            months=monthly,
            indicator_ids=sorted(grouped),
            source_snapshot_id=bundle.snapshot_id,
            status="COMPLETED" if grouped else "PARTIAL",
            transformation_version=self.version,
            event_overrides=event_overrides,
            assumptions=[
                "Feature projections are deterministic scenario inputs, not official forecasts",
                "Recent change is capped to +/-5%, decays by 0.65, and has role-specific horizon caps",
                "Stale and rejected observations are excluded from numeric features",
            ],
        )
