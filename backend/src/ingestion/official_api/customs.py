"""Korea Customs Service Itemtrade XML adapter."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List

from src.config.credential_validation import get_credential
from src.ingestion.official_api.base_adapter import (
    BaseOfficialApiAdapter,
    CanonicalObservation,
    ProviderContractError,
)


class CustomsAdapter(BaseOfficialApiAdapter):
    BASE_URL = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
    AVAILABILITY_POLICY_ID = "CUSTOMS_MONTH_END_PLUS_25D_APPROX.v1"
    NORMALIZATION_VERSION = "customs_itemtrade.v1"

    def __init__(self, opener: Callable[..., Any] | None = None, timeout_seconds: float = 15):
        self.opener = opener or urllib.request.urlopen
        self.timeout_seconds = timeout_seconds
        self.last_error_code = None

    def fetch(self, request_params: Dict[str, Any]) -> bytes:
        api_key = get_credential("CUSTOMS_API_KEY") or get_credential("DATA_GO_KR_API_KEY")
        if not api_key:
            raise ProviderContractError("NOT_CONFIGURED")
        start = request_params.get("strtYymm") or request_params.get("start_year_month")
        end = request_params.get("endYymm") or request_params.get("end_year_month") or start
        hs_code = request_params.get("hsSgn") or request_params.get("hs_code")
        if not start or not end or not hs_code:
            raise ProviderContractError("INVALID_REQUEST")
        query = urllib.parse.urlencode({
            "serviceKey": api_key,
            "strtYymm": str(start),
            "endYymm": str(end),
            "hsSgn": str(hs_code),
        })
        request = urllib.request.Request(
            f"{self.BASE_URL}?{query}",
            headers={"Accept": "application/xml", "User-Agent": "KB-AI/1.0"},
        )
        with self.opener(request, timeout=self.timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                raise ProviderContractError(f"HTTP_{response.status}")
            return response.read()

    def parse(self, raw_response: Any) -> List[Dict[str, Any]]:
        if not raw_response:
            return []
        try:
            root = ET.fromstring(raw_response)
        except (ET.ParseError, TypeError) as exc:
            raise ProviderContractError("MALFORMED_RESPONSE") from exc
        result_code = (root.findtext(".//resultCode") or "").strip()
        if result_code != "00":
            raise ProviderContractError(f"PROVIDER_RESULT_{result_code or 'MISSING'}")
        return [
            {child.tag: (child.text or "").strip() for child in item}
            for item in root.findall(".//item")
        ]

    @staticmethod
    def _period(value: str) -> tuple[str, date]:
        normalized = value.strip().replace(".", "").replace("-", "")
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("year must be YYYY.MM or YYYYMM")
        year, month = int(normalized[:4]), int(normalized[4:])
        return f"{year:04d}{month:02d}", date(year, month, 1)

    @classmethod
    def _availability(cls, observed_at: date) -> str:
        month_end = date(
            observed_at.year,
            observed_at.month,
            monthrange(observed_at.year, observed_at.month)[1],
        )
        available_date = month_end + timedelta(days=25)
        return datetime.combine(
            available_date,
            datetime.min.time(),
            tzinfo=timezone(timedelta(hours=9)),
        ).isoformat()

    def normalize(self, raw_observations: List[Dict[str, Any]]) -> List[CanonicalObservation]:
        output: list[CanonicalObservation] = []
        for item in raw_observations:
            hs_code = str(item.get("hsCode") or item.get("hsSgn") or "").strip()
            if not hs_code or hs_code == "-" or str(item.get("year", "")).strip() == "총계":
                continue
            try:
                period, observed_at = self._period(str(item["year"]))
                import_value = Decimal(str(item["impDlr"]).replace(",", ""))
                import_weight = Decimal(str(item["impWgt"]).replace(",", ""))
            except (KeyError, ValueError, InvalidOperation):
                continue
            if import_value < 0 or import_weight < 0:
                continue
            source_id = f"SRC-CUSTOMS-ITEMTRADE-HS{hs_code}-ALL-ORIGINS"
            material = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            revision_id = f"CUSTOMS-{period}-{hashlib.sha256(material.encode()).hexdigest()[:16].upper()}"
            available_at = self._availability(observed_at)
            common = {
                "frequency": "MONTHLY",
                "observed_at": observed_at.isoformat(),
                "released_at": available_at,
                "available_at": available_at,
                "source_id": source_id,
                "revision_id": revision_id,
                "normalization_version": self.NORMALIZATION_VERSION,
                "availability_policy_id": self.AVAILABILITY_POLICY_ID,
                "assumptions": [
                    "All origin countries are aggregated by the provider response",
                    "Availability uses a versioned month-end-plus-25-day approximation",
                ],
            }
            output.extend([
                CanonicalObservation(
                    indicator_id=f"CUSTOMS_IMPORT_VALUE_USD_HS{hs_code}",
                    value=float(import_value),
                    unit="USD",
                    **common,
                ),
                CanonicalObservation(
                    indicator_id=f"CUSTOMS_IMPORT_WEIGHT_KG_HS{hs_code}",
                    value=float(import_weight),
                    unit="KG",
                    **common,
                ),
            ])
            if import_weight > 0:
                output.append(CanonicalObservation(
                    indicator_id=f"CUSTOMS_IMPORT_UNIT_PRICE_USD_PER_KG_HS{hs_code}",
                    value=float(import_value / import_weight),
                    unit="USD_PER_KG",
                    **common,
                ))
        return output

    def process(self, request_params: Dict[str, Any]) -> List[CanonicalObservation]:
        observations = super().process(request_params)
        requested_indicator = request_params.get("indicator_id")
        if not requested_indicator:
            return observations
        return [item for item in observations if item.indicator_id == requested_indicator]
