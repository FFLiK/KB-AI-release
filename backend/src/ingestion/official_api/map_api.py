"""Fail-closed and deterministic Kakao/Naver geocoding adapter."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from src.config.credential_validation import get_credential
from src.normalization.address_normalizer import normalize_korean_address
from src.validation.geo_validator import calculate_haversine_distance_meters


class MapApiAdapter:
    KAKAO_GEOCODE_URL = "https://dapi.kakao.com/v2/local/search/address.json"
    KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
    NAVER_GEOCODE_URL = "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode"

    def __init__(self, opener: Callable[..., Any] | None = None, timeout_seconds: float = 15):
        self.opener = opener or urllib.request.urlopen
        self.timeout_seconds = timeout_seconds
        self._success_cache: dict[str, tuple[Decimal, Decimal, dict[str, Any]]] = {}

    @staticmethod
    def _coordinates(latitude: Any, longitude: Any) -> tuple[Decimal, Decimal] | None:
        try:
            lat = Decimal(str(latitude))
            lon = Decimal(str(longitude))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if not (Decimal("-90") <= lat <= Decimal("90")):
            return None
        if not (Decimal("-180") <= lon <= Decimal("180")):
            return None
        return lat, lon

    @staticmethod
    def _error_metadata(provider: str, exc: Exception) -> dict[str, Any]:
        if isinstance(exc, urllib.error.HTTPError):
            provider_code = None
            try:
                payload = json.loads(exc.read())
                if isinstance(payload, dict):
                    provider_code = payload.get("code") or payload.get("errorType")
            except Exception:
                pass
            if exc.code == 401:
                reason = f"{provider}_AUTHENTICATION_FAILED"
            elif exc.code == 403:
                reason = f"{provider}_NOT_AUTHORIZED"
            elif exc.code == 429:
                reason = f"{provider}_RATE_LIMITED"
            else:
                reason = f"{provider}_HTTP_{exc.code}"
            metadata = {"geocode_status": "PROVIDER_ERROR", "provider": provider, "reason": reason}
            if provider_code is not None:
                metadata["provider_error_code"] = str(provider_code)
            return metadata
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return {"geocode_status": "PROVIDER_ERROR", "provider": provider, "reason": f"{provider}_TIMEOUT"}
        return {"geocode_status": "PROVIDER_ERROR", "provider": provider, "reason": f"{provider}_FAILURE"}

    def geocode_address(self, address_text: str) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        return self.resolve_location(address_text)

    def resolve_location(
        self,
        address_text: str,
        *,
        store_latitude: float | None = None,
        store_longitude: float | None = None,
        administrative_area_codes: list[str] | None = None,
        source_context: str | None = None,
        allow_administrative_fallback: bool = True,
    ) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        query = normalize_korean_address(address_text)
        from src.normalization.venue_normalizer import administrative_area_names, venue_search_forms

        area_names = administrative_area_names(administrative_area_codes)
        keyword_forms = venue_search_forms(
            address_text,
            administrative_area_codes=administrative_area_codes,
            source_context=source_context,
        )
        if not query:
            return None, None, {"geocode_status": "FAILED", "reason": "EMPTY_ADDRESS"}
        cache_key = "|".join([
            query,
            str(store_latitude or ""),
            str(store_longitude or ""),
            ",".join(sorted(administrative_area_codes or [])),
            normalize_korean_address(source_context or "")[:160],
            str(allow_administrative_fallback),
        ])
        cached = self._success_cache.get(cache_key)
        if cached is not None:
            latitude, longitude, metadata = cached
            return latitude, longitude, {**metadata, "cache_hit": True}

        attempted: list[str] = []
        failures: list[str] = []
        ambiguous: list[dict[str, Any]] = []
        not_found_count = 0
        kakao_key = get_credential("KAKAO_REST_API_KEY")
        if kakao_key:
            attempted.append("KAKAO_ADDRESS")
            latitude, longitude, metadata = self._geocode_kakao(query, kakao_key)
            if latitude is not None:
                stored = {**metadata, "cache_hit": False}
                self._success_cache[cache_key] = (latitude, longitude, stored)
                return latitude, longitude, stored
            if metadata.get("geocode_status") == "AMBIGUOUS":
                ambiguous.append(metadata)
            elif metadata.get("geocode_status") == "NOT_FOUND":
                not_found_count += 1
            elif metadata.get("reason"):
                failures.append(str(metadata["reason"]))

            for form_index, keyword_form in enumerate(keyword_forms):
                attempted.append(f"KAKAO_KEYWORD:{keyword_form}")
                latitude, longitude, metadata = self._geocode_kakao_keyword(
                    keyword_form,
                    kakao_key,
                    store_latitude=store_latitude,
                    store_longitude=store_longitude,
                    administrative_area_codes=area_names,
                    source_context=source_context or "",
                    allow_administrative_fallback=allow_administrative_fallback,
                )
                metadata = {
                    **metadata,
                    "attempted_queries": keyword_forms[:form_index + 1],
                    "administrative_area_names": area_names,
                }
                if latitude is not None:
                    stored = {**metadata, "cache_hit": False}
                    self._success_cache[cache_key] = (latitude, longitude, stored)
                    return latitude, longitude, stored
                if metadata.get("geocode_status") == "AMBIGUOUS":
                    ambiguous.append(metadata)
                elif metadata.get("geocode_status") == "NOT_FOUND":
                    not_found_count += 1
                elif metadata.get("reason"):
                    failures.append(str(metadata["reason"]))
            attempted.append("KAKAO_KEYWORD")
            latitude, longitude, metadata = self._geocode_kakao_keyword(
                query,
                kakao_key,
                store_latitude=store_latitude,
                store_longitude=store_longitude,
                administrative_area_codes=administrative_area_codes or [],
                source_context=source_context or "",
                allow_administrative_fallback=allow_administrative_fallback,
            )
            if latitude is not None:
                stored = {**metadata, "cache_hit": False}
                self._success_cache[cache_key] = (latitude, longitude, stored)
                return latitude, longitude, stored
            if metadata.get("geocode_status") == "AMBIGUOUS":
                ambiguous.append(metadata)
            elif metadata.get("geocode_status") == "NOT_FOUND":
                not_found_count += 1
            elif metadata.get("reason"):
                failures.append(str(metadata["reason"]))

            if (
                latitude is None
                and metadata.get("geocode_status") == "NOT_FOUND"
                and allow_administrative_fallback
                and administrative_area_codes
            ):
                attempted.append("KAKAO_ADMINISTRATIVE_AREA")
                latitude, longitude, metadata = self._geocode_kakao_keyword(
                    " ".join(area_names or administrative_area_codes),
                    kakao_key,
                    store_latitude=store_latitude,
                    store_longitude=store_longitude,
                    administrative_area_codes=area_names or administrative_area_codes,
                    source_context=source_context or query,
                    allow_administrative_fallback=True,
                )
                if latitude is not None:
                    metadata["match_type"] = "ADMINISTRATIVE_AREA_FALLBACK"
                    metadata["precision"] = "REPRESENTATIVE_AREA_POINT"
                    stored = {**metadata, "cache_hit": False}
                    self._success_cache[cache_key] = (latitude, longitude, stored)
                    return latitude, longitude, stored
                if metadata.get("geocode_status") == "AMBIGUOUS":
                    ambiguous.append(metadata)
                elif metadata.get("geocode_status") == "NOT_FOUND":
                    not_found_count += 1
                elif metadata.get("reason"):
                    failures.append(str(metadata["reason"]))

        naver_id = get_credential("NAVER_CLIENT_ID")
        naver_secret = get_credential("NAVER_CLIENT_SECRET")
        if naver_id and naver_secret:
            attempted.append("NAVER_ADDRESS")
            latitude, longitude, metadata = self._geocode_naver(query, naver_id, naver_secret)
            if latitude is not None:
                stored = {**metadata, "cache_hit": False}
                self._success_cache[cache_key] = (latitude, longitude, stored)
                return latitude, longitude, stored
            if metadata.get("geocode_status") == "AMBIGUOUS":
                ambiguous.append(metadata)
            elif metadata.get("geocode_status") == "NOT_FOUND":
                not_found_count += 1
            elif metadata.get("reason"):
                failures.append(str(metadata["reason"]))

        if not attempted:
            return None, None, {
                "geocode_status": "NOT_CONFIGURED",
                "reason": "Kakao or Naver geocoding credentials are required",
            }
        if ambiguous:
            candidate_count = max(int(item.get("candidate_count") or 0) for item in ambiguous)
            return None, None, {
                "geocode_status": "AMBIGUOUS",
                "providers_attempted": attempted,
                "candidate_count": candidate_count,
                "reason": "NO_CLEAR_TOP_RANKED_LOCATION",
            }
        if failures:
            return None, None, {
                "geocode_status": "PROVIDER_ERROR",
                "providers_attempted": attempted,
                "failure_codes": failures,
                "reason": failures[-1],
            }
        return None, None, {
            "geocode_status": "NOT_FOUND",
            "providers_attempted": attempted,
            "candidate_count": 0,
            "resolution_attempt_count": not_found_count,
        }
    def _read_json(self, request: urllib.request.Request, provider: str) -> dict[str, Any]:
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                if getattr(response, "status", 200) != 200:
                    raise urllib.error.HTTPError(request.full_url, response.status, "provider error", {}, None)
                payload = json.loads(response.read())
        except Exception as exc:
            metadata = self._error_metadata(provider, exc)
            raise GeocodingProviderError(metadata) from exc
        if not isinstance(payload, dict):
            raise GeocodingProviderError({
                "geocode_status": "PROVIDER_ERROR",
                "provider": provider,
                "reason": f"{provider}_MALFORMED_RESPONSE",
            })
        return payload

    def select_kakao_candidate(
        self,
        query: str,
        payload: dict[str, Any],
    ) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            return None, None, {"geocode_status": "PROVIDER_ERROR", "provider": "KAKAO", "reason": "KAKAO_MALFORMED_RESPONSE"}
        if not documents:
            return None, None, {"geocode_status": "NOT_FOUND", "provider": "KAKAO", "candidate_count": 0}
        normalized_query = normalize_korean_address(query)
        road_matches: list[tuple[dict[str, Any], str]] = []
        lot_matches: list[tuple[dict[str, Any], str]] = []
        for document in documents:
            if not isinstance(document, dict):
                continue
            road = document.get("road_address") or {}
            lot = document.get("address") or {}
            road_name = str(road.get("address_name") or "") if isinstance(road, dict) else ""
            lot_name = str(lot.get("address_name") or document.get("address_name") or "") if isinstance(lot, dict) else ""
            if road_name and normalize_korean_address(road_name) == normalized_query:
                road_matches.append((document, road_name))
            if lot_name and normalize_korean_address(lot_name) == normalized_query:
                lot_matches.append((document, lot_name))

        candidates = road_matches if len(road_matches) == 1 else lot_matches if not road_matches and len(lot_matches) == 1 else []
        match_type = "EXACT_ROAD_ADDRESS" if candidates is road_matches and candidates else "EXACT_LOT_ADDRESS"
        if not candidates:
            return None, None, {
                "geocode_status": "AMBIGUOUS",
                "provider": "KAKAO",
                "candidate_count": len(documents),
                "reason": "NO_UNIQUE_EXACT_ADDRESS_MATCH",
            }
        document, matched_address = candidates[0]
        coordinates = self._coordinates(document.get("y"), document.get("x"))
        if coordinates is None:
            return None, None, {
                "geocode_status": "PROVIDER_ERROR",
                "provider": "KAKAO",
                "reason": "INVALID_COORDINATES",
            }
        return coordinates[0], coordinates[1], {
            "geocode_status": "SUCCESS",
            "provider": "KAKAO",
            "candidate_count": len(documents),
            "match_type": match_type,
            "matched_address": matched_address,
        }

    def _geocode_kakao(self, query: str, api_key: str) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        url = f"{self.KAKAO_GEOCODE_URL}?{urllib.parse.urlencode({'query': query})}"
        request = urllib.request.Request(url, headers={
            "Authorization": f"KakaoAK {api_key}",
            "Accept": "application/json",
            "User-Agent": "KB-AI/1.0",
        })
        try:
            return self.select_kakao_candidate(query, self._read_json(request, "KAKAO"))
        except GeocodingProviderError as exc:
            return None, None, exc.metadata

    @staticmethod
    def _context_tokens(value: str) -> set[str]:
        normalized = normalize_korean_address(value).lower()
        return {
            token for token in normalized.replace(",", " ").replace(">", " ").split()
            if len(token) >= 2
        }

    def select_kakao_keyword_candidate(
        self,
        query: str,
        payload: dict[str, Any],
        *,
        store_latitude: float | None = None,
        store_longitude: float | None = None,
        administrative_area_codes: list[str] | None = None,
        source_context: str = "",
        allow_administrative_fallback: bool = True,
    ) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            return None, None, {
                "geocode_status": "PROVIDER_ERROR",
                "provider": "KAKAO",
                "reason": "KAKAO_MALFORMED_RESPONSE",
            }
        ranked: list[tuple[float, dict[str, Any], Decimal, Decimal, float | None]] = []
        query_tokens = self._context_tokens(query)
        context_tokens = self._context_tokens(source_context)
        area_codes = {normalize_korean_address(item).lower() for item in administrative_area_codes or []}
        road_tokens = ("로", "길", "교차", "거리", "road", "bridge", "intersection")
        for document in documents:
            if not isinstance(document, dict):
                continue
            coordinates = self._coordinates(document.get("y"), document.get("x"))
            if coordinates is None:
                continue
            latitude, longitude = coordinates
            address = str(
                document.get("road_address_name")
                or document.get("address_name")
                or document.get("place_name")
                or ""
            )
            place = str(document.get("place_name") or "")
            category = str(document.get("category_name") or "")
            haystack = normalize_korean_address(f"{address} {place} {category}").lower()
            score = float(sum(8 for token in query_tokens if token in haystack))
            score += float(sum(2 for token in context_tokens if token in haystack))
            matched_area = next((code for code in sorted(area_codes) if code and code in haystack), None)
            if matched_area:
                score += 30
            distance: float | None = None
            if store_latitude is not None and store_longitude is not None:
                distance = calculate_haversine_distance_meters(
                    store_latitude, store_longitude, float(latitude), float(longitude)
                )
                score += max(0.0, 20.0 - distance / 500.0)
            is_road_segment = any(token in query.lower() for token in road_tokens)
            if is_road_segment and any(token in haystack for token in road_tokens):
                score += 12
            ranked.append((score, document, latitude, longitude, distance))
        if not ranked:
            return None, None, {
                "geocode_status": "NOT_FOUND", "provider": "KAKAO", "candidate_count": 0,
            }
        ranked.sort(key=lambda item: (-item[0], item[4] if item[4] is not None else float("inf"),
                                      str(item[1].get("id") or item[1].get("place_name") or "")))
        top = ranked[0]
        if len(ranked) > 1 and abs(top[0] - ranked[1][0]) < 1.0:
            return None, None, {
                "geocode_status": "AMBIGUOUS",
                "provider": "KAKAO",
                "candidate_count": len(ranked),
                "reason": "TOP_CANDIDATES_TIED",
            }
        document = top[1]
        address = str(
            document.get("road_address_name")
            or document.get("address_name")
            or document.get("place_name")
            or query
        )
        category = str(document.get("category_name") or "")
        method = "PLACE_KEYWORD"
        if any(token in query.lower() for token in road_tokens):
            method = "LANDMARK_ROAD_SEGMENT"
        elif allow_administrative_fallback and not query_tokens:
            method = "ADMINISTRATIVE_AREA_FALLBACK"
        metadata: dict[str, Any] = {
            "geocode_status": "SUCCESS",
            "provider": "KAKAO",
            "candidate_count": len(ranked),
            "match_type": method,
            "matched_address": address,
            "category": category,
            "candidate_score": round(top[0], 3),
        }
        if top[4] is not None:
            metadata["distance_meters"] = round(top[4], 2)
        return top[2], top[3], metadata

    def select_kakao_keyword_candidate(
        self,
        query: str,
        payload: dict[str, Any],
        *,
        store_latitude: float | None = None,
        store_longitude: float | None = None,
        administrative_area_codes: list[str] | None = None,
        source_context: str = "",
        allow_administrative_fallback: bool = True,
    ) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        """Rank only defensible public-place candidates for a normalized venue."""
        from src.normalization.venue_normalizer import administrative_area_names, venue_search_forms

        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            return None, None, {
                "geocode_status": "PROVIDER_ERROR",
                "provider": "KAKAO",
                "reason": "KAKAO_MALFORMED_RESPONSE",
            }
        forms = venue_search_forms(query, administrative_area_codes=administrative_area_codes)
        normalized_query = forms[0] if forms else normalize_korean_address(query)
        query_tokens = self._context_tokens(normalized_query)
        context_tokens = self._context_tokens(source_context)
        area_names = administrative_area_names(administrative_area_codes)
        normalized_areas = {normalize_korean_address(item).lower() for item in area_names}
        ko = lambda *points: "".join(chr(point) for point in points)
        public_categories = (
            ko(0xAD11, 0xC7A5), ko(0xAD00, 0xAD11), ko(0xCEE8, 0xBCA4, 0xC158),
            ko(0xC804, 0xC2DC), ko(0xACF5, 0xC6D0), ko(0xB3C4, 0xB85C),
            ko(0xB2E4, 0xB9AC), ko(0xACF5, 0xACF5), ko(0xBB38, 0xD654),
            ko(0xAD00, 0xAD11), ko(0xD589, 0xC0AC), ko(0xACF5, 0xC5F0),
            "plaza", "convention", "park", "road", "bridge", "public", "landmark", "venue",
        )
        commercial_categories = (
            ko(0xC74C, 0xC2DD, 0xC810), ko(0xCE74, 0xD398), ko(0xC8FC, 0xC810),
            ko(0xC1FC, 0xD551), "restaurant", "cafe", "bar", "food", "retail", "shopping",
        )
        ranked: list[tuple[float, dict[str, Any], Decimal, Decimal, float | None, int]] = []
        rejected: list[dict[str, str]] = []
        for document in documents:
            if not isinstance(document, dict):
                continue
            coordinates = self._coordinates(document.get("y"), document.get("x"))
            if coordinates is None:
                rejected.append({"id": str(document.get("id") or ""), "reason": "INVALID_COORDINATES"})
                continue
            latitude, longitude = coordinates
            address = str(
                document.get("road_address_name")
                or document.get("address_name")
                or document.get("place_name")
                or ""
            )
            place = str(document.get("place_name") or "")
            category = str(document.get("category_name") or "")
            haystack = normalize_korean_address(f"{address} {place} {category}").lower()
            category_normalized = normalize_korean_address(category).lower()
            allowed_public = any(token in category_normalized for token in public_categories)
            commercial = any(token in category_normalized for token in commercial_categories)
            if commercial and not allowed_public:
                rejected.append({"id": str(document.get("id") or place), "reason": "COMMERCIAL_CATEGORY"})
                continue
            overlap = sum(1 for token in query_tokens if token in haystack)
            if query_tokens and overlap == 0:
                rejected.append({"id": str(document.get("id") or place), "reason": "INSUFFICIENT_TOKEN_OVERLAP"})
                continue
            score = float(overlap * 12)
            score += float(sum(2 for token in context_tokens if token in haystack))
            matched_area = next((area for area in sorted(normalized_areas) if area and area in haystack), None)
            if matched_area:
                score += 30
            if allowed_public:
                score += 8
            distance: float | None = None
            if store_latitude is not None and store_longitude is not None:
                distance = calculate_haversine_distance_meters(
                    store_latitude, store_longitude, float(latitude), float(longitude)
                )
                score += max(0.0, 6.0 - distance / 1_000.0)
            ranked.append((score, document, latitude, longitude, distance, overlap))
        if not ranked:
            return None, None, {
                "geocode_status": "NOT_FOUND",
                "provider": "KAKAO",
                "candidate_count": 0,
                "administrative_area_names": area_names,
                "rejected_candidates": rejected,
            }
        ranked.sort(key=lambda item: (
            -item[0], item[4] if item[4] is not None else float("inf"),
            str(item[1].get("id") or item[1].get("place_name") or ""),
        ))
        ranked_metadata = [
            {
                "id": str(item[1].get("id") or item[1].get("place_name") or ""),
                "score": round(item[0], 3),
                "token_overlap": item[5],
                "distance_meters": round(item[4], 2) if item[4] is not None else None,
            }
            for item in ranked
        ]
        top = ranked[0]
        if len(ranked) > 1 and abs(top[0] - ranked[1][0]) < 2.0:
            return None, None, {
                "geocode_status": "AMBIGUOUS",
                "provider": "KAKAO",
                "candidate_count": len(ranked),
                "reason": "TOP_CANDIDATES_TIED",
                "administrative_area_names": area_names,
                "ranked_candidates": ranked_metadata,
                "rejected_candidates": rejected,
            }
        document = top[1]
        address = str(
            document.get("road_address_name")
            or document.get("address_name")
            or document.get("place_name")
            or normalized_query
        )
        category = str(document.get("category_name") or "")
        method = "PLACE_KEYWORD"
        if normalize_korean_address(normalized_query).casefold() in {"coex", ko(0xCF54, 0xC5D1, 0xC2A4)}:
            method = "COEX_REPRESENTATIVE_POINT"
        if any(token in normalized_query.casefold() for token in ("road", "bridge", "intersection")):
            method = "LANDMARK_ROAD_SEGMENT"
        metadata: dict[str, Any] = {
            "geocode_status": "SUCCESS",
            "provider": "KAKAO",
            "candidate_count": len(ranked),
            "match_type": method,
            "matched_address": address,
            "category": category,
            "candidate_score": round(top[0], 3),
            "administrative_area_names": area_names,
            "ranked_candidates": ranked_metadata,
            "rejected_candidates": rejected,
        }
        if top[4] is not None:
            metadata["distance_meters"] = round(top[4], 2)
        return top[2], top[3], metadata
    def _geocode_kakao_keyword(
        self,
        query: str,
        api_key: str,
        **selection_context: Any,
    ) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        url = f"{self.KAKAO_KEYWORD_URL}?{urllib.parse.urlencode({'query': query, 'size': 15})}"
        request = urllib.request.Request(url, headers={
            "Authorization": f"KakaoAK {api_key}",
            "Accept": "application/json",
            "User-Agent": "KB-AI/1.0",
        })
        try:
            payload = self._read_json(request, "KAKAO")
        except GeocodingProviderError as exc:
            return None, None, exc.metadata
        return self.select_kakao_keyword_candidate(query, payload, **selection_context)
    def _geocode_naver(
        self, query: str, client_id: str, client_secret: str
    ) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        url = f"{self.NAVER_GEOCODE_URL}?{urllib.parse.urlencode({'query': query})}"
        request = urllib.request.Request(url, headers={
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
            "Accept": "application/json",
            "User-Agent": "KB-AI/1.0",
        })
        try:
            payload = self._read_json(request, "NAVER")
        except GeocodingProviderError as exc:
            return None, None, exc.metadata
        addresses = payload.get("addresses", [])
        if not isinstance(addresses, list) or not addresses:
            return None, None, {"geocode_status": "NOT_FOUND", "provider": "NAVER", "candidate_count": 0}
        normalized_query = normalize_korean_address(query)
        road = [item for item in addresses if normalize_korean_address(str(item.get("roadAddress") or "")) == normalized_query]
        lot = [item for item in addresses if normalize_korean_address(str(item.get("jibunAddress") or "")) == normalized_query]
        selected = road if len(road) == 1 else lot if not road and len(lot) == 1 else []
        if not selected:
            return None, None, {
                "geocode_status": "AMBIGUOUS", "provider": "NAVER",
                "candidate_count": len(addresses), "reason": "NO_UNIQUE_EXACT_ADDRESS_MATCH",
            }
        coordinates = self._coordinates(selected[0].get("y"), selected[0].get("x"))
        if coordinates is None:
            return None, None, {"geocode_status": "PROVIDER_ERROR", "provider": "NAVER", "reason": "INVALID_COORDINATES"}
        return coordinates[0], coordinates[1], {
            "geocode_status": "SUCCESS", "provider": "NAVER", "candidate_count": len(addresses),
            "match_type": "EXACT_ROAD_ADDRESS" if selected is road else "EXACT_LOT_ADDRESS",
            "matched_address": selected[0].get("roadAddress") or selected[0].get("jibunAddress"),
        }


class GeocodingProviderError(RuntimeError):
    def __init__(self, metadata: dict[str, Any]):
        super().__init__(str(metadata.get("reason") or "PROVIDER_ERROR"))
        self.metadata = metadata
