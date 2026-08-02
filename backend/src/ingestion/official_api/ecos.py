"""Bank of Korea ECOS adapter bound to explicit indicator registry entries."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List

from src.config.credential_validation import get_credential
from src.ingestion.official_api.base_adapter import (
    BaseOfficialApiAdapter,
    CanonicalObservation,
    ProviderContractError,
)
from src.registries.official_indicator_registry import provider_indicators


class ECOSAdapter(BaseOfficialApiAdapter):
    BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
    NORMALIZATION_VERSION = "ecos_registry.v1"

    def __init__(self, opener: Callable[..., Any] | None = None, timeout_seconds: float = 15):
        self.opener = opener or urllib.request.urlopen
        self.timeout_seconds = timeout_seconds
        self.last_error_code = None

    def fetch(self, request_params: Dict[str, Any]) -> bytes:
        api_key = get_credential("ECOS_API_KEY")
        if not api_key:
            raise ProviderContractError("NOT_CONFIGURED")
        required = ("stat_code", "period_type", "start_date", "end_date", "item_code")
        if any(not request_params.get(key) for key in required):
            raise ProviderContractError("INVALID_REQUEST")
        segments = [
            str(request_params["stat_code"]),
            str(request_params["period_type"]),
            str(request_params["start_date"]),
            str(request_params["end_date"]),
            str(request_params["item_code"]),
        ]
        if request_params.get("item_code2"):
            segments.append(str(request_params["item_code2"]))
        encoded = "/".join(urllib.parse.quote(item, safe="*") for item in segments)
        url = f"{self.BASE_URL}/{api_key}/json/kr/1/100/{encoded}"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "KB-AI/1.0"})
        with self.opener(request, timeout=self.timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                raise ProviderContractError(f"HTTP_{response.status}")
            return response.read()

    def parse(self, raw_response: Any) -> List[Dict[str, Any]]:
        if not raw_response:
            return []
        try:
            payload = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
            raise ProviderContractError("MALFORMED_RESPONSE") from exc
        if not isinstance(payload, dict):
            raise ProviderContractError("MALFORMED_RESPONSE")
        if "RESULT" in payload:
            code = str(payload["RESULT"].get("CODE") or "MISSING")
            raise ProviderContractError(f"PROVIDER_RESULT_{code}")
        section = payload.get("StatisticSearch")
        if not isinstance(section, dict):
            raise ProviderContractError("MALFORMED_RESPONSE")
        rows = section.get("row", [])
        if not isinstance(rows, list):
            raise ProviderContractError("MALFORMED_RESPONSE")
        return rows

    @staticmethod
    def _available_at(observed_at: date, lag_days: int) -> str:
        month_end = date(
            observed_at.year,
            observed_at.month,
            monthrange(observed_at.year, observed_at.month)[1],
        )
        available_date = month_end + timedelta(days=lag_days)
        return datetime.combine(
            available_date,
            datetime.min.time(),
            tzinfo=timezone(timedelta(hours=9)),
        ).isoformat()

    def normalize(self, raw_observations: List[Dict[str, Any]]) -> List[CanonicalObservation]:
        definitions = provider_indicators("ECOS")
        by_series = {
            str(definition["provider_series_code"]): (indicator_id, definition)
            for indicator_id, definition in definitions.items()
        }
        output: list[CanonicalObservation] = []
        for item in raw_observations:
            series = ":".join(filter(None, [
                str(item.get("STAT_CODE") or ""),
                str(item.get("ITEM_CODE1") or ""),
                str(item.get("ITEM_CODE2") or ""),
            ]))
            match = by_series.get(series)
            if match is None:
                continue
            indicator_id, definition = match
            period = str(item.get("TIME") or "")
            if len(period) != 6 or not period.isdigit():
                continue
            observed_at = date(int(period[:4]), int(period[4:]), 1)
            lag_days = int(definition["availability_lag_days"])
            available_at = self._available_at(observed_at, lag_days)
            material = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            revision_id = f"ECOS-{period}-{hashlib.sha256(material.encode()).hexdigest()[:16].upper()}"
            source_id = "SRC-ECOS-" + series.replace(":", "-").replace("*", "ALL")
            try:
                value = float(item["DATA_VALUE"])
            except (KeyError, TypeError, ValueError):
                continue
            output.append(CanonicalObservation(
                indicator_id=indicator_id,
                value=value,
                unit=str(definition["unit"]),
                frequency=str(definition["frequency"]),
                observed_at=observed_at.isoformat(),
                released_at=available_at,
                available_at=available_at,
                source_id=source_id,
                revision_id=revision_id,
                normalization_version=self.NORMALIZATION_VERSION,
                availability_policy_id=str(definition["availability_policy"]),
                assumptions=[str(definition["release_policy"])],
            ))
        return output

    def process(self, request_params: Dict[str, Any]) -> List[CanonicalObservation]:
        observations = super().process(request_params)
        requested_indicator = request_params.get("indicator_id")
        if not requested_indicator:
            return observations
        return [item for item in observations if item.indicator_id == requested_indicator]
