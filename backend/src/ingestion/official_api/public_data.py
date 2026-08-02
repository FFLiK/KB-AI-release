"""Public Data Portal adapter for non-numeric store reference snapshots."""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict

from src.config.credential_validation import get_credential
from src.contracts.store_reference import BusinessLocationRecord, StoreReferenceSnapshot
from src.ingestion.official_api.base_adapter import ProviderContractError, provider_failure_code


@dataclass(frozen=True)
class ParsedStoreResponse:
    provider_reference_month: str
    items: list[dict[str, Any]]


class PublicDataStoreAdapter:
    BASE_URL = "https://apis.data.go.kr/B553077/api/open/sdsc2"
    SOURCE_ID = "SRC-PUBLIC-DATA-SDSC-STORE"
    ENDPOINT_FIELDS = {
        "storeOne": ({"key"}, {"key"}),
        "storeListInRadius": (
            {"radius", "cx", "cy"},
            {"radius", "cx", "cy", "numOfRows", "pageNo", "indsLclsCd", "indsMclsCd", "indsSclsCd"},
        ),
        "storeListInDong": (
            {"divId", "key"},
            {"divId", "key", "numOfRows", "pageNo", "indsLclsCd", "indsMclsCd", "indsSclsCd"},
        ),
        "storeListInUpjong": (
            {"divId", "key"},
            {"divId", "key", "numOfRows", "pageNo"},
        ),
        "storeListByDate": (
            {"startDate", "endDate"},
            {"startDate", "endDate", "numOfRows", "pageNo"},
        ),
    }

    def __init__(self, opener: Callable[..., Any] | None = None, timeout_seconds: float = 15):
        self.opener = opener or urllib.request.urlopen
        self.timeout_seconds = timeout_seconds
        self.last_error_code: str | None = None

    def fetch(self, request_params: Dict[str, Any]) -> bytes:
        api_key = get_credential("PUBLIC_DATA_API_KEY") or get_credential("DATA_GO_KR_API_KEY")
        if not api_key:
            raise ProviderContractError("NOT_CONFIGURED")
        endpoint = str(request_params.get("endpoint") or "storeOne")
        contract = self.ENDPOINT_FIELDS.get(endpoint)
        if contract is None:
            raise ProviderContractError("UNSUPPORTED_ENDPOINT")
        required, allowed = contract
        if any(not request_params.get(field) for field in required):
            raise ProviderContractError("INVALID_REQUEST")
        unexpected = set(request_params) - allowed - {"endpoint"}
        if unexpected:
            raise ProviderContractError("INVALID_REQUEST")
        query_values = {
            "serviceKey": api_key,
            "type": "json",
            **{key: request_params[key] for key in allowed if request_params.get(key) is not None},
        }
        query = urllib.parse.urlencode(query_values)
        request = urllib.request.Request(
            f"{self.BASE_URL}/{endpoint}?{query}",
            headers={"Accept": "application/json", "User-Agent": "KB-AI/1.0"},
        )
        with self.opener(request, timeout=self.timeout_seconds) as response:
            if getattr(response, "status", 200) != 200:
                raise ProviderContractError(f"HTTP_{response.status}")
            return response.read()

    @staticmethod
    def _raise_provider_error(code: str) -> None:
        if code in {"30", "31"}:
            raise ProviderContractError("AUTHENTICATION_FAILED")
        if code in {"22", "429"}:
            raise ProviderContractError("RATE_LIMITED")
        raise ProviderContractError(f"PROVIDER_RESULT_{code or 'MISSING'}")

    def parse(self, raw_response: Any) -> ParsedStoreResponse:
        if not raw_response:
            return ParsedStoreResponse(provider_reference_month="", items=[])
        try:
            payload = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            try:
                root = ET.fromstring(raw_response)
            except (ET.ParseError, TypeError) as exc:
                raise ProviderContractError("MALFORMED_RESPONSE") from exc
            code = str(root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "")
            self._raise_provider_error(code)
            raise AssertionError("unreachable")
        if not isinstance(payload, dict):
            raise ProviderContractError("MALFORMED_RESPONSE")
        header = payload.get("header")
        body = payload.get("body")
        if not isinstance(header, dict) or not isinstance(body, dict):
            raise ProviderContractError("MALFORMED_RESPONSE")
        code = str(header.get("resultCode") or "")
        if code != "00":
            self._raise_provider_error(code)
        reference_month = str(header.get("stdrYm") or "")
        if len(reference_month) != 6 or not reference_month.isdigit():
            raise ProviderContractError("MISSING_REFERENCE_MONTH")
        items = body.get("items", [])
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ProviderContractError("MALFORMED_RESPONSE")
        return ParsedStoreResponse(provider_reference_month=reference_month, items=items)

    def normalize(
        self,
        parsed: ParsedStoreResponse,
        source_revision_id: str | None = None,
    ) -> list[BusinessLocationRecord]:
        output: list[BusinessLocationRecord] = []
        for item in parsed.items:
            material = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            revision = source_revision_id or f"SDSC-{hashlib.sha256(material.encode()).hexdigest()[:16].upper()}"
            try:
                output.append(BusinessLocationRecord(
                    business_id=str(item["bizesId"]),
                    business_name=str(item["bizesNm"]),
                    branch_name=str(item.get("brchNm") or "") or None,
                    industry_large_code=str(item.get("indsLclsCd") or "") or None,
                    industry_large_name=str(item.get("indsLclsNm") or "") or None,
                    industry_middle_code=str(item.get("indsMclsCd") or "") or None,
                    industry_middle_name=str(item.get("indsMclsNm") or "") or None,
                    industry_small_code=str(item.get("indsSclsCd") or "") or None,
                    industry_small_name=str(item.get("indsSclsNm") or "") or None,
                    standard_industry_code=str(item.get("ksicCd") or "") or None,
                    standard_industry_name=str(item.get("ksicNm") or "") or None,
                    lot_address=str(item.get("lnoAdr") or "") or None,
                    road_address=str(item.get("rdnmAdr") or "") or None,
                    latitude=float(item["lat"]),
                    longitude=float(item["lon"]),
                    province_code=str(item.get("ctprvnCd") or "") or None,
                    province_name=str(item.get("ctprvnNm") or "") or None,
                    district_code=str(item.get("signguCd") or "") or None,
                    district_name=str(item.get("signguNm") or "") or None,
                    administrative_dong_code=str(item.get("adongCd") or "") or None,
                    administrative_dong_name=str(item.get("adongNm") or "") or None,
                    legal_dong_code=str(item.get("ldongCd") or "") or None,
                    legal_dong_name=str(item.get("ldongNm") or "") or None,
                    postal_code=str(item.get("newZipcd") or "") or None,
                    provider_reference_month=parsed.provider_reference_month,
                    source_id=self.SOURCE_ID,
                    source_revision_id=revision,
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return output

    def _retrieve(self, request_params: Dict[str, Any]) -> tuple[bytes, ParsedStoreResponse, list[BusinessLocationRecord]]:
        raw = self.fetch(request_params)
        parsed = self.parse(raw)
        if not parsed.items:
            raise ProviderContractError("EMPTY_RESPONSE")
        body_hash = hashlib.sha256(raw).hexdigest()
        revision = f"SDSC-{parsed.provider_reference_month}-{body_hash[:16].upper()}"
        records = self.normalize(parsed, revision)
        if not records:
            raise ProviderContractError("NO_VALID_RECORDS")
        return raw, parsed, records

    def process(self, request_params: Dict[str, Any]) -> list[BusinessLocationRecord]:
        self.last_error_code = None
        try:
            return self._retrieve(request_params)[2]
        except Exception as exc:
            self.last_error_code = provider_failure_code(exc)
            return []

    def build_snapshot(
        self,
        request_params: Dict[str, Any],
        retrieved_at: datetime,
    ) -> StoreReferenceSnapshot | None:
        self.last_error_code = None
        try:
            raw, parsed, records = self._retrieve(request_params)
            body_hash = hashlib.sha256(raw).hexdigest()
            revision = records[0].source_revision_id
            snapshot_id = f"SRS-{body_hash[:24].upper()}"
            return StoreReferenceSnapshot(
                snapshot_id=snapshot_id,
                endpoint=str(request_params.get("endpoint") or "storeOne"),
                provider_reference_month=parsed.provider_reference_month,
                retrieved_at=retrieved_at,
                source_id=self.SOURCE_ID,
                source_revision_id=revision,
                body_hash=body_hash,
                records=records,
                raw_payload=parsed.items,
            )
        except Exception as exc:
            self.last_error_code = provider_failure_code(exc)
            return None
