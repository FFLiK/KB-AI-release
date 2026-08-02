"""Bridge newer primary-source decisions across delayed official indicator releases."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation

from src.contracts.canonical_event import CanonicalEvent
from src.normalization.indicator_normalizer import normalize_official_indicator, normalize_official_unit
from src.contracts.official import (
    CanonicalObservation,
    ObservationFrequency,
    ObservationQualityStatus,
    OfficialDataBundle,
    OfficialEventOverride,
)


EVENT_INDICATORS = {
    "BASE_RATE_INCREASE": "BASE_RATE",
    "BASE_RATE_DECREASE": "BASE_RATE",
    "BASE_RATE_HOLD": "BASE_RATE",
}
REQUIRED_ATTRIBUTE_PATHS = {
    "attributes.official_indicator_id",
    "attributes.official_new_value",
    "attributes.official_value_unit",
}


def _event_type(event: CanonicalEvent) -> str:
    return str(event.event_type).split(".")[-1]


def _source_tier(event: CanonicalEvent) -> str:
    return str(event.source_tier).split(".")[-1]


def _record(
    event: CanonicalEvent,
    indicator_id: str,
    value: Decimal | None,
    unit: str | None,
    latest: CanonicalObservation | None,
    status: str,
    reason: str,
    observation_id: str | None = None,
) -> OfficialEventOverride:
    return OfficialEventOverride(
        event_id=event.event_id,
        indicator_id=indicator_id,
        effective_date=event.start_date,
        event_value=value,
        unit=unit,
        latest_official_observed_at=latest.observed_at if latest else None,
        latest_official_value=latest.value if latest else None,
        status=status,
        reason_code=reason,
        synthetic_observation_id=observation_id,
        source_ids=event.source_ids,
        source_revision_ids=event.source_revision_ids,
    )


def apply_official_event_bridge(
    bundle: OfficialDataBundle,
    events: list[CanonicalEvent] | None,
) -> tuple[OfficialDataBundle, list[OfficialEventOverride]]:
    """Return a derived bundle plus auditable apply/skip/expiry decisions."""
    if not events:
        return bundle, []
    derived = bundle.model_copy(deep=True)
    decisions: list[OfficialEventOverride] = []
    seen_semantic_identities: set[tuple[object, ...]] = set()
    for event in sorted(events, key=lambda item: (item.start_date, item.event_id)):
        mapped_indicator = EVENT_INDICATORS.get(_event_type(event))
        if not mapped_indicator:
            continue
        raw_value = event.attributes.get("official_normalized_new_value", event.attributes.get("official_new_value"))
        raw_unit = event.attributes.get("official_value_unit")
        declared_indicator = normalize_official_indicator(event.attributes.get("official_indicator_id") or mapped_indicator)
        try:
            value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            value = None
            value_valid = False
        else:
            value_valid = value.is_finite()
        unit = normalize_official_unit(raw_unit)
        latest = max(
            (
                item for item in derived.observations
                if item.indicator_id == mapped_indicator
                and item.quality_status in {ObservationQualityStatus.VALID, ObservationQualityStatus.REVISED}
            ),
            key=lambda item: (item.observed_at, item.available_at, item.observation_id),
            default=None,
        )
        semantic_identity = (event.actor_org_id, declared_indicator, event.start_date, _event_type(event), str(value), unit)
        if semantic_identity in seen_semantic_identities:
            continue
        seen_semantic_identities.add(semantic_identity)
        evidenced_paths = {path for evidence in event.evidence for path in evidence.field_paths}
        if _source_tier(event) != "OFFICIAL_PRIMARY":
            decisions.append(_record(event, mapped_indicator, value, unit, latest, "INELIGIBLE", "SOURCE_NOT_OFFICIAL_PRIMARY"))
            continue
        actor_text = " ".join(filter(None, [event.actor_org_id, event.actor_org_raw])).casefold()
        if mapped_indicator == "BASE_RATE" and any(token in actor_text for token in ("fomc", "federal reserve", "\ubbf8\uad6d \uc5f0\ubc29")):
            decisions.append(_record(event, mapped_indicator, value, unit, latest, "INELIGIBLE", "ACTOR_NOT_AUTHORIZED_FOR_BASE_RATE"))
            continue
        if declared_indicator != mapped_indicator:
            decisions.append(_record(event, mapped_indicator, value, unit, latest, "INELIGIBLE", "INDICATOR_MISMATCH"))
            continue
        if not value_valid or not unit or not REQUIRED_ATTRIBUTE_PATHS.issubset(evidenced_paths):
            decisions.append(_record(event, mapped_indicator, value, unit, latest, "INELIGIBLE", "VALUE_OR_UNIT_NOT_EXPLICITLY_EVIDENCED"))
            continue
        if latest is None:
            decisions.append(_record(event, mapped_indicator, value, unit, latest, "INELIGIBLE", "NO_OFFICIAL_BASELINE_OBSERVATION"))
            continue
        if latest.unit.upper() != unit.upper():
            decisions.append(_record(event, mapped_indicator, value, unit, latest, "INELIGIBLE", "UNIT_MISMATCH"))
            continue
        if event.start_date <= latest.observed_at:
            decisions.append(_record(event, mapped_indicator, value, unit, latest, "EXPIRED", "OFFICIAL_SERIES_CAUGHT_UP"))
            continue
        if event.start_date > bundle.as_of_date:
            decisions.append(_record(event, mapped_indicator, value, unit, latest, "INELIGIBLE", "EVENT_NOT_EFFECTIVE_AS_OF_ANALYSIS"))
            continue
        identity = f"{event.event_id}|{mapped_indicator}|{event.start_date}|{value}|{unit}"
        observation_id = "OVR-" + hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
        released = datetime.combine(event.start_date, time.min, tzinfo=UTC)
        derived.observations.append(CanonicalObservation(
            observation_id=observation_id,
            indicator_id=mapped_indicator,
            value=value,
            unit=unit,
            frequency=ObservationFrequency.DAILY,
            observed_at=event.start_date,
            released_at=released,
            available_at=released,
            source_id=event.source_ids[0],
            source_revision_id=event.source_revision_ids[0],
            vintage_id=f"EVENT-{event.event_id}",
            normalization_rule_id="OFFICIAL_EVENT_BRIDGE_V1",
            assumptions=[
                "Temporary official-event override until the registered observation series catches up",
                f"Bridged from validated event {event.event_id}",
            ],
            quality_status=ObservationQualityStatus.VALID,
        ))
        decisions.append(_record(
            event, mapped_indicator, value, unit, latest, "APPLIED",
            "NEWER_OFFICIAL_EVENT_BRIDGES_STALE_SERIES", observation_id,
        ))
    return derived, decisions
