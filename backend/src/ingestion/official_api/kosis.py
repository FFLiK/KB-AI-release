"""KOSIS adapter bound to the registered national consumer-price series."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timezone, timedelta
from typing import Any, Callable, Dict, List

from src.config.credential_validation import get_credential
from src.ingestion.official_api.base_adapter import (
    BaseOfficialApiAdapter,
    CanonicalObservation,
    ProviderContractError,
)
from src.registries.official_indicator_registry import provider_indicators


class KOSISAdapter(BaseOfficialApiAdapter):
    BASE_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    NORMALIZATION_VERSION = "kosis_registry.v1"

    def __init__(self, opener: Callable[..., Any] | None = None, timeout_seconds: float = 15):
        self.opener = opener or urllib.request.urlopen
        self.timeout_seconds = timeout_seconds
        self.last_error_code = None

    def fetch(self, request_params: Dict[str, Any]) -> bytes:
        api_key = get_credential("KOSIS_API_KEY")
        if not api_key:
            raise ProviderContractError("NOT_CONFIGURED")
        required = ("orgId", "tblId", "objL1", "itmId", "prdSe", "startPrdDe", "endPrdDe")
        if any(not request_params.get(key) for key in required):
            raise ProviderContractError("INVALID_REQUEST")
        query = urllib.parse.urlencode({
            "method": "getList",
            "apiKey": api_key,
            "orgId": request_params["orgId"],
            "tblId": request_params["tblId"],
            "objL1": request_params["objL1"],
            "itmId": request_params["itmId"],
            "prdSe": request_params["prdSe"],
            "startPrdDe": request_params["startPrdDe"],
            "endPrdDe": request_params["endPrdDe"],
            "format": "json",
            "jsonVD": "Y",
        })
        request = urllib.request.Request(
            f"{self.BASE_URL}?{query}",
            headers={"Accept": "application/json", "User-Agent": "KB-AI/1.0"},
        )
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
        if isinstance(payload, dict) and "err" in payload:
            code = str(payload.get("err") or "MISSING")
            if code == "11":
                raise ProviderContractError("AUTHENTICATION_FAILED")
            raise ProviderContractError(f"PROVIDER_RESULT_{code}")
        if not isinstance(payload, list):
            raise ProviderContractError("MALFORMED_RESPONSE")
        if not all(isinstance(row, dict) for row in payload):
            raise ProviderContractError("MALFORMED_RESPONSE")
        return payload

    @staticmethod
    def _normalized_label(value: Any) -> str:
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))

    @staticmethod
    def _last_change_at(value: Any) -> str | None:
        digits = "".join(character for character in str(value or "") if character.isdigit())
        if len(digits) < 8:
            return None
        changed = date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        return datetime.combine(changed, time.min, tzinfo=timezone(timedelta(hours=9))).isoformat()

    def normalize(self, raw_observations: List[Dict[str, Any]]) -> List[CanonicalObservation]:
        definitions = provider_indicators("KOSIS")
        output: list[CanonicalObservation] = []
        for item in raw_observations:
            series = ":".join([
                str(item.get("ORG_ID") or ""),
                str(item.get("TBL_ID") or ""),
                str(item.get("ITM_ID") or ""),
                "NATIONAL" if str(item.get("C1_NM") or "").strip() == "전국" else "OTHER",
            ])
            matched = next(
                (
                    (indicator_id, definition)
                    for indicator_id, definition in definitions.items()
                    if str(definition["provider_series_code"]) == series
                ),
                None,
            )
            if matched is None or str(item.get("PRD_SE") or "") != "M":
                continue
            indicator_id, definition = matched
            if self._normalized_label(item.get("UNIT_NM")) != self._normalized_label(definition["provider_unit_label"]):
                continue
            period = str(item.get("PRD_DE") or "")
            if len(period) != 6 or not period.isdigit():
                continue
            available_at = self._last_change_at(item.get("LST_CHN_DE"))
            if available_at is None:
                continue
            try:
                value = float(item["DT"])
            except (KeyError, TypeError, ValueError):
                continue
            material = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            revision_id = f"KOSIS-{period}-{hashlib.sha256(material.encode()).hexdigest()[:16].upper()}"
            output.append(CanonicalObservation(
                indicator_id=indicator_id,
                value=value,
                unit=str(definition["unit"]),
                frequency=str(definition["frequency"]),
                observed_at=date(int(period[:4]), int(period[4:]), 1).isoformat(),
                released_at=available_at,
                available_at=available_at,
                source_id="SRC-KOSIS-101-DT-1J22003-T-NATIONAL",
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
