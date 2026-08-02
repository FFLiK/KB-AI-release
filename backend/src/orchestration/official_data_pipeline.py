"""Validated official-data ingestion with immutable vintages and monthly transforms."""
from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from src.contracts.official import (
    CanonicalObservation,
    FreshnessRecord,
    FrequencyTransform,
    ObservationFrequency,
    ObservationQualityStatus,
    OfficialCollectionStatus,
    OfficialDataBundle,
    OfficialDataRequest,
    OfficialDataStatus,
    OfficialIndicatorCollectionResult,
    OfficialIndicatorMetadata,
    SourceVintage,
)
from src.operations.metrics import metrics
from src.registries.official_indicator_registry import load_official_indicator_registry
from src.storage.analysis_repository import OfficialDataRepository


def _stable_id(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24].upper()


def _aware(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _indicator_metadata(request: OfficialDataRequest) -> OfficialIndicatorMetadata:
    registry = load_official_indicator_registry()
    definition = registry.get(request.indicator_id, {})
    role = str(definition.get("feature_role") or "UNMAPPED")
    affected = {
        "REVENUE_DEMAND": "REVENUE",
        "DOMESTIC_INGREDIENT_COST": "DOMESTIC_INGREDIENT_COST",
        "IMPORTED_INGREDIENT_COST": "IMPORTED_INGREDIENT_COST",
        "INTEREST_RATE": "INTEREST_PAYMENT",
    }.get(role, "NONE")
    return OfficialIndicatorMetadata(
        indicator_id=request.indicator_id,
        display_name=str(definition.get("display_name") or request.indicator_id.replace("_", " ").title()),
        provider=str(definition.get("provider") or request.provider),
        provider_series_code=definition.get("provider_series_code"),
        feature_role=role,
        unit=definition.get("unit"),
        frequency=definition.get("frequency"),
        max_age_days=request.max_age_days if request.max_age_days is not None else definition.get("max_age_days"),
        affected_model_dimension=affected,
        description=definition.get("description"),
    )


class FakeOfficialAdapter:
    """Deterministic fixture adapter; values must be supplied by the caller."""

    def __init__(self, observations: list[dict[str, Any]] | None = None):
        self.observations = observations or []

    def process(self, request_params: dict[str, Any]) -> list[dict[str, Any]]:
        indicator = request_params.get("indicator_id")
        return [item for item in self.observations if not indicator or item.get("indicator_id") == indicator]


class OfficialDataPipeline:
    def __init__(self, adapters: dict[str, Any] | None = None, repository: OfficialDataRepository | None = None):
        self.adapters = {key.upper(): value for key, value in (adapters or {}).items()}
        self.repository = repository

    def run(self, run_id: str, as_of_date: date, requests: list[OfficialDataRequest]) -> OfficialDataBundle:
        if not requests:
            return OfficialDataBundle(
                snapshot_id=_stable_id("ODS-", f"{run_id}|{as_of_date}|empty"),
                as_of_date=as_of_date,
                status=OfficialDataStatus.SKIPPED,
                missing_indicators=[],
            )

        observations: list[CanonicalObservation] = []
        vintages: list[SourceVintage] = []
        freshness: list[FreshnessRecord] = []
        collection_results: list[OfficialIndicatorCollectionResult] = []
        transforms: list[FrequencyTransform] = []
        missing: list[str] = []
        errors: dict[str, str] = {}
        retrieved_at = datetime.now(UTC)

        for request in requests:
            metadata = _indicator_metadata(request)
            adapter = self.adapters.get(request.provider.upper())
            if adapter is None:
                metrics.increment("official_provider_requests_total")
                metrics.increment("official_provider_failure_total")
                missing.append(request.indicator_id)
                errors[request.provider] = "PROVIDER_NOT_CONFIGURED"
                collection_results.append(OfficialIndicatorCollectionResult(
                    provider=request.provider,
                    indicator_id=request.indicator_id,
                    required=request.required,
                    status=OfficialCollectionStatus.FAILED if request.required else OfficialCollectionStatus.MISSING,
                    failure_code="PROVIDER_NOT_CONFIGURED",
                    failure_detail="The configured provider adapter was unavailable.",
                    missing_data_behavior="The model continued without this optional indicator." if not request.required else "The required indicator was unavailable.",
                    metadata=metadata,
                ))
                continue
            params = dict(request.request_params)
            params.setdefault("indicator_id", request.indicator_id)
            metrics.increment("official_provider_requests_total")
            started = time.perf_counter()
            try:
                raw_items = adapter.process(params)
            except Exception as exc:
                raw_items = []
                errors[request.provider] = f"{type(exc).__name__}: {exc}"
                metrics.increment("official_provider_failure_total")
            finally:
                metrics.observe(
                    "official_provider_latency_ms",
                    (time.perf_counter() - started) * 1000,
                )
            if not raw_items:
                metrics.increment("official_provider_empty_result_total")
                missing.append(request.indicator_id)
                errors.setdefault(request.provider, "NO_OBSERVATIONS")
                provider_error = errors[request.provider]
                failure_code = "NO_OBSERVATIONS" if provider_error == "NO_OBSERVATIONS" else "PROVIDER_ERROR"
                collection_results.append(OfficialIndicatorCollectionResult(
                    provider=request.provider,
                    indicator_id=request.indicator_id,
                    required=request.required,
                    status=OfficialCollectionStatus.FAILED if request.required else OfficialCollectionStatus.MISSING,
                    failure_code=failure_code,
                    failure_detail=provider_error,
                    missing_data_behavior="The model continued without this optional indicator." if not request.required else "The required indicator was unavailable.",
                    metadata=metadata,
                ))
                continue

            raw_payload = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in raw_items]
            metrics.increment("official_records_fetched_total", len(raw_payload))
            vintage_retrieved_at = (
                _aware(raw_payload[0]["retrieved_at"]) if raw_payload[0].get("retrieved_at") else retrieved_at
            )
            body = json.dumps(raw_payload, sort_keys=True, default=str, separators=(",", ":"))
            body_hash = hashlib.sha256(body.encode()).hexdigest()
            source_id = str(raw_payload[0].get("source_id", f"SRC-{request.provider.upper()}"))
            provider_revision = raw_payload[0].get("source_revision_id") or raw_payload[0].get("revision_id")
            source_revision_id = str(provider_revision or body_hash[:16])
            revision_basis = "PROVIDER" if provider_revision else "CONTENT_HASH"
            vintage_id = _stable_id("VNT-", f"{request.provider}|{source_revision_id}|{body_hash}")
            vintage = SourceVintage(
                vintage_id=vintage_id,
                provider=request.provider,
                source_id=source_id,
                source_revision_id=source_revision_id,
                revision_basis=revision_basis,
                retrieved_at=vintage_retrieved_at,
                body_hash=body_hash,
                observation_count=0,
                raw_payload=raw_payload,
            )
            vintages.append(vintage)
            normalized: list[CanonicalObservation] = []
            for index, item in enumerate(raw_payload):
                try:
                    observed_at = date.fromisoformat(str(item["observed_at"])[:10])
                    released_value = item.get("released_at")
                    if not released_value:
                        errors[f"{request.provider}:{index}"] = "MISSING_RELEASE_METADATA"
                        continue
                    released_at = _aware(released_value)
                    available_at = _aware(item.get("available_at") or released_at)
                    if observed_at > as_of_date or released_at.date() > as_of_date or available_at.date() > as_of_date:
                        errors[f"{request.provider}:{index}"] = "NOT_AVAILABLE_AS_OF_ANALYSIS_DATE"
                        continue
                    frequency = ObservationFrequency(str(item.get("frequency", "MONTHLY")).upper())
                    identity = f"{request.indicator_id}|{observed_at}|{item['value']}|{vintage_id}|{index}"
                    normalized.append(CanonicalObservation(
                        observation_id=_stable_id("OBS-", identity),
                        indicator_id=request.indicator_id,
                        value=Decimal(str(item["value"])),
                        unit=str(item.get("unit", "VALUE")),
                        frequency=frequency,
                        observed_at=observed_at,
                        released_at=released_at,
                        available_at=available_at,
                        source_id=source_id,
                        source_revision_id=source_revision_id,
                        vintage_id=vintage_id,
                        normalization_rule_id=str(item.get("normalization_rule_id") or item.get("normalization_version") or "indicator.v1"),
                        availability_policy_id=item.get("availability_policy_id"),
                        assumptions=list(item.get("assumptions") or []),
                    ))
                except Exception as exc:
                    errors[f"{request.provider}:{index}"] = f"INVALID_OBSERVATION: {exc}"

            validated_count = len(normalized)
            metrics.increment("official_records_accepted_total", validated_count)
            metrics.increment(
                "official_records_rejected_total",
                max(0, len(raw_payload) - validated_count),
            )
            if request.target_frequency == ObservationFrequency.MONTHLY:
                input_observation_ids = [item.observation_id for item in normalized]
                normalized, generated = self._to_monthly(normalized, request.transform)
                if generated:
                    transforms.append(FrequencyTransform(
                        indicator_id=request.indicator_id,
                        from_frequency=ObservationFrequency.DAILY,
                        to_frequency=ObservationFrequency.MONTHLY,
                        method=request.transform,
                        input_observation_ids=input_observation_ids,
                        output_observation_ids=[item.observation_id for item in normalized],
                    ))
            vintage.observation_count = len(normalized)
            if not normalized:
                missing.append(request.indicator_id)
                collection_results.append(OfficialIndicatorCollectionResult(
                    provider=request.provider,
                    indicator_id=request.indicator_id,
                    required=request.required,
                    status=OfficialCollectionStatus.FAILED if request.required else OfficialCollectionStatus.MISSING,
                    failure_code="NO_VALID_OBSERVATIONS",
                    failure_detail="Provider rows were returned but none were valid and available as of the analysis date.",
                    missing_data_behavior="The model continued without this optional indicator." if not request.required else "The required indicator was unavailable.",
                    metadata=metadata,
                ))
                continue
            latest = max(item.observed_at for item in normalized)
            age = (as_of_date - latest).days
            stale = request.max_age_days is not None and age > request.max_age_days
            if stale:
                normalized = [item.model_copy(update={"quality_status": ObservationQualityStatus.STALE}) for item in normalized]
            metrics.observe("official_freshness_age_days", age)
            freshness.append(FreshnessRecord(
                indicator_id=request.indicator_id,
                latest_observed_at=latest,
                age_days=age,
                max_age_days=request.max_age_days,
                is_stale=stale,
            ))
            ordered = sorted(normalized, key=lambda item: (item.observed_at, item.available_at, item.observation_id))
            latest_item = ordered[-1]
            previous_item = ordered[-2] if len(ordered) > 1 else None
            absolute_change = latest_item.value - previous_item.value if previous_item else None
            collection_results.append(OfficialIndicatorCollectionResult(
                provider=request.provider,
                indicator_id=request.indicator_id,
                required=request.required,
                status=OfficialCollectionStatus.COMPLETED,
                observation_count=len(ordered),
                latest_observation_id=ordered[-1].observation_id,
                previous_observation_id=ordered[-2].observation_id if len(ordered) > 1 else None,
                latest_value=latest_item.value,
                previous_value=previous_item.value if previous_item else None,
                unit=latest_item.unit,
                absolute_change=absolute_change,
                percentage_change=(absolute_change / abs(previous_item.value) if previous_item and previous_item.value != 0 else None),
                latest_observed_at=latest_item.observed_at,
                latest_released_at=latest_item.released_at,
                latest_available_at=latest_item.available_at,
                freshness_age_days=age,
                freshness_max_age_days=request.max_age_days,
                freshness_status="STALE" if stale else "VALID",
                metadata=metadata,
            ))
            observations.extend(normalized)

        required_missing = {item.indicator_id for item in requests if item.required} & set(missing)
        if required_missing and not observations:
            status = OfficialDataStatus.FAILED
        elif missing or errors:
            status = OfficialDataStatus.PARTIAL
        else:
            status = OfficialDataStatus.COMPLETED
        metrics.increment("official_missing_indicator_total", len(set(missing)))
        metrics.increment(f"official_bundle_{status.value.lower()}_total")
        snapshot_material = "|".join(sorted(item.vintage_id for item in vintages)) or f"{run_id}|empty"
        bundle = OfficialDataBundle(
            snapshot_id=_stable_id("ODS-", snapshot_material),
            as_of_date=as_of_date,
            observations=sorted(observations, key=lambda item: (item.indicator_id, item.observed_at, item.observation_id)),
            source_vintages=vintages,
            frequency_transforms=transforms,
            freshness=freshness,
            collection_results=collection_results,
            missing_indicators=sorted(set(missing)),
            provider_errors=errors,
            status=status,
        )
        if self.repository:
            self.repository.save_bundle(run_id, bundle)
        return bundle

    @staticmethod
    def _to_monthly(items: list[CanonicalObservation], method: str) -> tuple[list[CanonicalObservation], bool]:
        if not any(item.frequency == ObservationFrequency.DAILY for item in items):
            return items, False
        grouped: dict[tuple[str, str], list[CanonicalObservation]] = defaultdict(list)
        passthrough = []
        for item in items:
            if item.frequency == ObservationFrequency.DAILY:
                grouped[(item.indicator_id, item.observed_at.strftime("%Y-%m"))].append(item)
            else:
                passthrough.append(item)
        for (indicator, month), values in grouped.items():
            values.sort(key=lambda item: (item.observed_at, item.available_at))
            if method.upper() == "AVERAGE":
                value = sum(item.value for item in values) / Decimal(len(values))
            elif method.upper() == "VOLATILITY":
                mean = sum(item.value for item in values) / Decimal(len(values))
                value = (sum((item.value - mean) ** 2 for item in values) / Decimal(len(values))).sqrt()
            else:
                value = values[-1].value
            base = values[-1]
            identity = f"{indicator}|{month}|{method}|{'|'.join(item.observation_id for item in values)}"
            passthrough.append(base.model_copy(update={
                "observation_id": _stable_id("OBS-", identity),
                "value": value,
                "frequency": ObservationFrequency.MONTHLY,
                "observed_at": date.fromisoformat(month + "-01"),
                "normalization_rule_id": f"daily_to_monthly.{method.lower()}.v1",
            }))
        return passthrough, True
