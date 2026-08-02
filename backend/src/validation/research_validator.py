from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from src.contracts.canonical_event import CanonicalEvent, CanonicalLocation, NormalizationRecord
from src.contracts.event_candidate import ExtractedEventCandidate
from src.contracts.research import ResearchRequest
from src.contracts.source_document import AccessStatus, SourceDocument
from src.normalization.date_normalizer import (
    DateNormalizationError, normalize_date, normalize_document_anchored_month,
)
from src.normalization.geo_normalizer import Geocoder
from src.normalization.industry_normalizer import IndustryNormalizer
from src.normalization.organization_normalizer import OrganizationNormalizer, normalize_text
from src.registries.event_registry import EventRegistry, RegistryValidationError, default_registry
from src.validation.evidence_validator import validate_event_evidence
from src.validation.geo_validator import calculate_haversine_distance_meters


FAILURE_CODES={"MISSING_REQUIRED_FIELD","ENUM_NOT_ALLOWED","DIRECTION_MECHANISM_NOT_ALLOWED","QUOTE_NOT_FOUND","OFFSET_MISMATCH","DATE_PARSE_FAILED","DATE_RANGE_INVALID","FORECAST_WINDOW_NOT_OVERLAPPED","LOCATION_AMBIGUOUS","GEO_PROVIDER_NOT_CONFIGURED","GEO_PROVIDER_ERROR","GEO_NOT_FOUND","OUTSIDE_SEARCH_RADIUS","INDUSTRY_NOT_RELEVANT","MECHANISM_NOT_SUPPORTED","SOURCE_UNAVAILABLE","SOURCE_UNTRUSTED","SOURCE_CONFLICT","DUPLICATE_EVENT","PROMPT_INJECTION_DETECTED"}

_ONGOING_EVIDENCE = re.compile(
    r"\b(?:ongoing|remains? (?:in )?effect|still active|until further notice|currently active|effective immediately|effective from)\b"
    r"|\ud604\uc7ac\s*(?:\uc9c4\ud589|\uc720\uc9c0|\uc2dc\ud589)|\uacc4\uc18d\s*(?:\uc9c4\ud589|\uc801\uc6a9)|\ubcc4\ub3c4\s*\ud574\uc81c\uc2dc",
    re.IGNORECASE,
)
_PRICE_EVENT_TYPES = {"WHOLESALE_PRICE_INCREASE", "WHOLESALE_PRICE_DECREASE"}


def _explicitly_ongoing(candidate: ExtractedEventCandidate) -> bool:
    return any(_ONGOING_EVIDENCE.search(item.quote) for item in candidate.evidence)


def _is_historical_price_context(
    candidate: ExtractedEventCandidate,
    start: date,
    published: date,
    as_of_date: date,
) -> bool:
    """A dated price article is explanatory context, not a current price series."""
    event_type = getattr(candidate.event_type, "value", candidate.event_type)
    return event_type in _PRICE_EVENT_TYPES and max(start, published) < as_of_date - timedelta(days=180)


def _temporal_evidence_offset(candidate: ExtractedEventCandidate, field_path: str, raw: str | None) -> int | None:
    if not raw:
        return None
    for evidence in candidate.evidence:
        if field_path in evidence.field_paths:
            index = evidence.quote.casefold().find(raw.casefold())
            if index >= 0:
                return evidence.start_offset + index
    return None


def _temporal_evidence_end(candidate: ExtractedEventCandidate, field_path: str, raw: str | None) -> int | None:
    start = _temporal_evidence_offset(candidate, field_path, raw)
    return start + len(raw) if start is not None and raw else None

@dataclass
class ValidationOutcome:
    candidate: ExtractedEventCandidate
    status: str
    failure_codes: list[str]
    event: CanonicalEvent | None = None
    retryable: bool = False
    retry_attempted: bool = False
    retry_outcome: str | None = None
    retry_candidate_id: str | None = None
    validation_metadata: dict[str, Any] = field(default_factory=dict)
    lifecycle_stages: list[str] = field(default_factory=lambda: ["DISCOVERED", "EXTRACTED"])


class ResearchEventValidator:
    def __init__(self,registry: EventRegistry | None=None,geocoder: Geocoder | None=None):
        self.registry=registry or default_registry(); self.geocoder=geocoder
        self.organizations=OrganizationNormalizer(); self.industries=IndustryNormalizer()

    def validate(self,candidate: ExtractedEventCandidate,documents: dict[str,SourceDocument],request: ResearchRequest) -> ValidationOutcome:
        candidate, numeric_codes, numeric_records = _normalize_official_attributes(candidate)
        if numeric_codes:
            return ValidationOutcome(candidate, "RETRYABLE", numeric_codes, None, True)
        codes=[]
        related=[]
        for ev in candidate.evidence:
            doc=documents.get(ev.source_id)
            if not doc or doc.revision_id != ev.source_revision_id or doc.access_status != AccessStatus.OK:
                codes.append("SOURCE_UNAVAILABLE")
            else:
                related.append(doc)
        if any(doc.security_flags for doc in related):
            return ValidationOutcome(candidate,"REJECTED",["PROMPT_INJECTION_DETECTED"],None,False)
        if "SOURCE_UNAVAILABLE" in codes:
            return ValidationOutcome(candidate,"REJECTED",sorted(set(codes)),None,False)
        try: config=self.registry.get(getattr(candidate.event_type, "value", candidate.event_type)); self.registry.validate_candidate(candidate)
        except RegistryValidationError as exc: return ValidationOutcome(candidate,"RETRYABLE",exc.codes,None,True)
        if related and all(getattr(doc.source_type, "value", doc.source_type) == "OTHER" for doc in related):
            codes.append("SOURCE_UNTRUSTED")
        snapshots={sid:doc.body_text for sid,doc in documents.items()}
        ok,evidence_errors=validate_event_evidence([x.model_dump() for x in candidate.evidence],snapshots)
        if not ok:
            codes.extend("OFFSET_MISMATCH" if "Offset" in error else "QUOTE_NOT_FOUND" for error in evidence_errors)
        evidenced_paths={path for ev in candidate.evidence for path in ev.field_paths}
        required_paths={"event_type","temporal.start_raw"}
        for idx,_ in enumerate(candidate.impacts):
            if not any(path.startswith(f"impacts[{idx}]") for path in evidenced_paths): required_paths.add(f"impacts[{idx}]")
        if not required_paths.issubset(evidenced_paths): codes.append("MISSING_REQUIRED_FIELD")
        published=related[0].published_at.date() if related and related[0].published_at else request.as_of_date
        start_anchor = None
        end_anchor = None
        try:
            start,start_rule=normalize_date(candidate.temporal.start_raw,published)
        except DateNormalizationError:
            try:
                start, start_rule, start_anchor = normalize_document_anchored_month(candidate.temporal.start_raw, related[0])
            except DateNormalizationError:
                failures = sorted(set(codes + ["DATE_PARSE_FAILED"]))
                terminal = {"PROMPT_INJECTION_DETECTED", "SOURCE_UNAVAILABLE"}
                status = "REJECTED" if terminal.intersection(failures) else "RETRYABLE"
                return ValidationOutcome(candidate, status, failures, None, status == "RETRYABLE", validation_metadata={"temporal_anchor_available": False})
        try:
            end,end_rule=normalize_date(candidate.temporal.end_raw,published)
        except DateNormalizationError:
            try:
                end, end_rule, end_anchor = normalize_document_anchored_month(candidate.temporal.end_raw, related[0])
            except DateNormalizationError:
                failures = sorted(set(codes + ["DATE_PARSE_FAILED"]))
                terminal = {"PROMPT_INJECTION_DETECTED", "SOURCE_UNAVAILABLE"}
                status = "REJECTED" if terminal.intersection(failures) else "RETRYABLE"
                return ValidationOutcome(candidate, status, failures, None, status == "RETRYABLE", validation_metadata={"temporal_anchor_available": False})
        if start is None:
            failures = sorted(set(codes + ["DATE_PARSE_FAILED"]))
            terminal = {"PROMPT_INJECTION_DETECTED", "SOURCE_UNAVAILABLE"}
            status = "REJECTED" if terminal.intersection(failures) else "RETRYABLE"
            return ValidationOutcome(candidate, status, failures, None, status == "RETRYABLE")
        if _is_historical_price_context(candidate, start, published, request.as_of_date):
            return ValidationOutcome(
                candidate, "REFERENCE_ONLY", sorted(set(codes + ["HISTORICAL_CONTEXT_ONLY"])), None, False,
                lifecycle_stages=[
                    "DISCOVERED", "EXTRACTED", "VALIDATION_ATTEMPTED", "EVIDENCE_VALIDATED",
                    "HISTORICAL_CONTEXT_RETAINED",
                ],
            )
        event_type = getattr(candidate.event_type, "value", candidate.event_type)
        bounded_bok_hold = event_type == "BASE_RATE_HOLD" and any(
            "next monetary-policy decision" in item.quote.casefold() or "next monetary policy decision" in item.quote.casefold()
            for item in candidate.evidence
        )
        if end is None and bounded_bok_hold:
            try:
                end, end_rule = normalize_date(str(candidate.attributes["next_decision_date"]), published)
            except (KeyError, DateNormalizationError):
                return ValidationOutcome(candidate, "REFERENCE_ONLY", sorted(set(codes + ["BOK_BOUNDED_PERIOD_NEXT_DECISION_UNVERIFIED"])), None, False)
        if end is None:
            if config["temporal_policy"] != "BOUNDED" and _explicitly_ongoing(candidate):
                end=request.forecast_end; end_rule="EXPLICIT_ONGOING_EVIDENCE_TO_FORECAST_END_V1"
            else:
                return ValidationOutcome(
                    candidate, "REFERENCE_ONLY", sorted(set(codes + ["MISSING_ONGOING_EVIDENCE"])), None, False,
                    lifecycle_stages=[
                        "DISCOVERED", "EXTRACTED", "VALIDATION_ATTEMPTED", "EVIDENCE_VALIDATED",
                        "TEMPORAL_EVIDENCE_INSUFFICIENT",
                    ],
                )
        if end and start>end: codes.append("DATE_RANGE_INVALID")
        if end and (end<request.forecast_start or start>request.forecast_end): codes.append("FORECAST_WINDOW_NOT_OVERLAPPED")
        if "FORECAST_WINDOW_NOT_OVERLAPPED" in codes:
            return ValidationOutcome(
                candidate,
                "REJECTED",
                sorted(set(codes)),
                None,
                False,
                lifecycle_stages=[
                    "DISCOVERED", "EXTRACTED", "VALIDATION_ATTEMPTED",
                    "EVIDENCE_VALIDATED", "TEMPORAL_VALIDATED", "OUTSIDE_FORECAST_WINDOW",
                ],
            )
        actor_id,actor_rule=self.organizations.normalize(candidate.actor_org_raw)
        industry_codes,industry_rule=self.industries.normalize(candidate.affected_industries_raw)
        if self.industries.relevance(request.business_type_code,industry_codes)==0: codes.append("INDUSTRY_NOT_RELEVANT")
        address=normalize_text(candidate.location.address_raw or candidate.location.area_raw)
        raw_venues = candidate.attributes.get("venues") or []
        if isinstance(raw_venues, str):
            raw_venues = [item.strip() for item in re.split(r"[,;|]", raw_venues) if item.strip()]
        area_text = (candidate.location.area_raw or "").casefold()
        broad_area = any(marker in area_text for marker in (
            "gangnam area", "major tourist attractions",
            "\uac15\ub0a8 \uc77c\ub300", "\uc8fc\uc694 \uad00\uad11\uc9c0", "\uac15\ub0a8 \uc9c0\uc5ed",
        ))
        unresolved_multi_venue = (
            getattr(candidate.domain, "value", candidate.domain) == "LOCAL"
            and (
                (len(raw_venues) > 1 and not candidate.attributes.get("venue_instance_id"))
                or (not candidate.location.address_raw and broad_area)
            )
        )
        if unresolved_multi_venue:
            codes.append("LOCATION_AMBIGUOUS")
        lat,lon=candidate.location.latitude,candidate.location.longitude; geocode_status="PROVIDED"
        geo_metadata: dict[str, Any] = {
            "configured_radius_meters": request.search_radius_m,
            "multi_venue_detected": unresolved_multi_venue,
            "candidate_count": 0,
            "match_method": "PROVIDED_COORDINATES" if lat is not None and lon is not None else None,
            "provider": "EXTRACTED_SOURCE" if lat is not None and lon is not None else None,
        }
        if config["geo_policy"] == "LOCATION_REQUIRED" and (lat is None or lon is None):
            if not self.geocoder:
                codes.append("GEO_PROVIDER_NOT_CONFIGURED")
                geocode_status="NOT_CONFIGURED"
            elif not address:
                codes.append("GEO_NOT_FOUND")
                geocode_status="NOT_FOUND"
            elif hasattr(self.geocoder, "resolve"):
                source_context="\n".join(doc.body_text[:2000] for doc in related)
                resolution=self.geocoder.resolve(
                    address,
                    store_latitude=request.store_location.latitude,
                    store_longitude=request.store_location.longitude,
                    administrative_area_codes=request.administrative_area_codes,
                    source_context=source_context,
                    allow_administrative_fallback=(
                        candidate.location.address_raw is None
                        and candidate.location.area_raw is not None
                    ),
                )
                geo_metadata.update(resolution.metadata)
                matches=resolution.candidates
                provider_status=resolution.status
                if provider_status == "SUCCESS" and len(matches) == 1:
                    match=matches[0]
                    lat,lon=match.latitude,match.longitude
                    address=match.address
                    geocode_status="SUCCESS"
                    geo_metadata.update({
                        "provider": match.provider or geo_metadata.get("provider"),
                        "match_method": match.match_method or geo_metadata.get("match_type"),
                        "candidate_count": int(geo_metadata.get("candidate_count") or len(matches)),
                    })
                elif provider_status == "NOT_CONFIGURED":
                    codes.append("GEO_PROVIDER_NOT_CONFIGURED"); geocode_status="NOT_CONFIGURED"
                elif provider_status == "PROVIDER_ERROR":
                    codes.append("GEO_PROVIDER_ERROR"); geocode_status="PROVIDER_ERROR"
                elif provider_status == "AMBIGUOUS" or len(matches) > 1:
                    codes.append("LOCATION_AMBIGUOUS"); geocode_status="AMBIGUOUS"
                else:
                    codes.append("GEO_NOT_FOUND"); geocode_status="NOT_FOUND"
            else:
                matches=self.geocoder.geocode(address)
                geo_metadata["candidate_count"]=len(matches)
                if len(matches)>1: codes.append("LOCATION_AMBIGUOUS"); geocode_status="AMBIGUOUS"
                elif len(matches)==0: codes.append("GEO_NOT_FOUND"); geocode_status="NOT_FOUND"
                else:
                    lat,lon=matches[0].latitude,matches[0].longitude
                    address=matches[0].address; geocode_status="SUCCESS"
        distance=None
        if (lat is not None and lon is not None and request.store_location.latitude is not None and request.store_location.longitude is not None and config["geo_policy"] == "LOCATION_REQUIRED"):
            distance=calculate_haversine_distance_meters(request.store_location.latitude,request.store_location.longitude,lat,lon)
            geo_metadata["distance_meters"]=round(distance,2)
            if distance>request.search_radius_m: codes.append("OUTSIDE_SEARCH_RADIUS")
        if codes:
            terminal={"PROMPT_INJECTION_DETECTED","SOURCE_UNAVAILABLE","FORECAST_WINDOW_NOT_OVERLAPPED","OUTSIDE_SEARCH_RADIUS","INDUSTRY_NOT_RELEVANT"}
            status="REJECTED" if terminal.intersection(codes) else "RETRYABLE"
            if "SOURCE_UNTRUSTED" in codes:
                return ValidationOutcome(candidate,"REFERENCE_ONLY",sorted(set(codes)),None,False,validation_metadata=geo_metadata,lifecycle_stages=["DISCOVERED","EXTRACTED","VALIDATION_ATTEMPTED","EVIDENCE_VALIDATED","SOURCE_UNTRUSTED"])
            stages=["DISCOVERED","EXTRACTED","VALIDATION_ATTEMPTED","EVIDENCE_VALIDATED","TEMPORAL_VALIDATED"]
            stages.extend(["GEO_VALIDATED","EXCLUDED_BY_DISTANCE"] if "OUTSIDE_SEARCH_RADIUS" in codes else ["VALIDATION_FAILED"])
            return ValidationOutcome(candidate,status,sorted(set(codes)),None,status=="RETRYABLE",validation_metadata=geo_metadata,lifecycle_stages=stages)
        normalized_title=normalize_text(candidate.title) or candidate.title
        target=normalize_text(candidate.target_subject_raw)
        target_id=("TARGET-"+hashlib.sha256(target.encode()).hexdigest()[:12].upper()) if target else None
        event_type = getattr(candidate.event_type, "value", candidate.event_type)
        if actor_id == "ORG-BOK" and candidate.attributes.get("official_indicator_id") == "BASE_RATE":
            fingerprint_source="|".join([
                "BANK_OF_KOREA", "BASE_RATE", start.isoformat(), event_type,
                str(candidate.attributes.get("official_previous_value") or ""),
                str(candidate.attributes.get("official_new_value") or ""),
                str(candidate.attributes.get("official_value_unit") or ""),
            ])
        else:
            fingerprint_source="|".join([candidate.event_family,str(candidate.event_type),address or "",start.isoformat(),actor_id or "",target_id or ""])
        fingerprint=hashlib.sha256(fingerprint_source.encode()).hexdigest()[:24]
        records=[*numeric_records,
            NormalizationRecord(field_path="title",raw_value=candidate.title,normalized_value=normalized_title,rule_id="NFKC_WHITESPACE_V1"),
            NormalizationRecord(field_path="temporal.start_raw",raw_value=candidate.temporal.start_raw,normalized_value=start.isoformat(),rule_id=start_rule, rule_version="DOCUMENT_ANCHORED_MONTH_YEAR_V1" if start_anchor else "v1", source_id=related[0].source_id if start_anchor else None, source_revision_id=related[0].revision_id if start_anchor else None, start_offset=_temporal_evidence_offset(candidate, "temporal.start_raw", candidate.temporal.start_raw), end_offset=_temporal_evidence_end(candidate, "temporal.start_raw", candidate.temporal.start_raw), anchor_source=start_anchor.source if start_anchor else None),
            NormalizationRecord(field_path="temporal.end_raw",raw_value=candidate.temporal.end_raw,normalized_value=end.isoformat() if end else None,rule_id=end_rule, rule_version="DOCUMENT_ANCHORED_MONTH_YEAR_V1" if end_anchor else "v1", source_id=related[0].source_id if end_anchor else None, source_revision_id=related[0].revision_id if end_anchor else None, start_offset=_temporal_evidence_offset(candidate, "temporal.end_raw", candidate.temporal.end_raw), end_offset=_temporal_evidence_end(candidate, "temporal.end_raw", candidate.temporal.end_raw), anchor_source=end_anchor.source if end_anchor else None),
            NormalizationRecord(field_path="actor_org_raw",raw_value=candidate.actor_org_raw,normalized_value=actor_id,rule_id=actor_rule),
            NormalizationRecord(field_path="affected_industries_raw",raw_value="|".join(candidate.affected_industries_raw),normalized_value="|".join(industry_codes),rule_id=industry_rule),
            NormalizationRecord(field_path="location",raw_value=candidate.location.address_raw or candidate.location.area_raw,normalized_value=address,rule_id="UNIQUE_CANDIDATE_ONLY_V1"),]
        source_ids=list(dict.fromkeys(ev.source_id for ev in candidate.evidence)); revisions=list(dict.fromkeys(ev.source_revision_id for ev in candidate.evidence))
        tiers=[getattr(doc.source_type,"value",str(doc.source_type)) for doc in related]; tier=sorted(tiers,key=lambda x:{"OFFICIAL_PRIMARY":0,"OFFICIAL_LOCAL_GOV":0,"OFFICIAL_SECONDARY":1,"FINANCIAL_INSTITUTION":2,"MAJOR_NEWS":3,"OTHER":9}.get(x,8))[0]
        event_id="EVT-"+fingerprint.upper()
        signal_enabled,signal_reason=self.registry.signal_eligibility(str(candidate.event_type))
        event=CanonicalEvent(event_id=event_id,candidate_ids=[candidate.candidate_id],research_run_id=candidate.research_run_id,
            domain=candidate.domain,event_family=candidate.event_family,event_type=candidate.event_type,title=normalized_title,
            actor_org_id=actor_id,actor_org_raw=candidate.actor_org_raw,target_subject_id=target_id,target_subject_raw=candidate.target_subject_raw,
            start_date=start,end_date=end,location=CanonicalLocation(
                text_raw=candidate.location.address_raw or candidate.location.area_raw,
                normalized_address=address,latitude=lat,longitude=lon,geocode_status=geocode_status,
                geocode_provider=geo_metadata.get("provider"),
                match_method=geo_metadata.get("match_method") or geo_metadata.get("match_type"),
                distance_meters=distance,
                candidate_count=int(geo_metadata.get("candidate_count") or 0),
                resolution_metadata=geo_metadata,
            ),
            affected_industry_codes=industry_codes,impacts=candidate.impacts,attributes=candidate.attributes,evidence=candidate.evidence,
            source_ids=source_ids,source_revision_ids=revisions,source_tier=tier,validation_status="ACCEPTED",normalization_records=records,
            fingerprint=fingerprint,signal_enabled=signal_enabled,signal_eligibility_reason=signal_reason,registry_version=self.registry.version)
        return ValidationOutcome(candidate,"ACCEPTED",[],event,False,validation_metadata=geo_metadata,lifecycle_stages=["DISCOVERED","EXTRACTED","VALIDATION_ATTEMPTED","EVIDENCE_VALIDATED","TEMPORAL_VALIDATED","GEO_VALIDATED","INSTANCE_ELIGIBLE"])
from src.normalization.numeric_unit_normalizer import normalize_numeric_unit
from src.normalization.indicator_normalizer import normalize_official_indicator


def _normalize_official_attributes(candidate: ExtractedEventCandidate) -> tuple[ExtractedEventCandidate, list[str], list[NormalizationRecord]]:
    """Normalize explicit policy values while retaining their raw extraction."""
    attrs = dict(candidate.attributes)
    raw_new = attrs.get("official_new_value")
    raw_unit = attrs.get("official_value_unit")
    if raw_new in {None, ""} and raw_unit in {None, ""}:
        return candidate, [], []
    try:
        new = normalize_numeric_unit(raw_new, raw_unit)
    except ValueError:
        return candidate, ["OFFICIAL_NUMERIC_UNIT_INVALID"], []
    attrs["official_new_value_raw"] = str(raw_new)
    attrs["official_new_value"] = str(new.normalized_value)
    attrs["official_normalized_new_value"] = str(new.normalized_value)
    attrs["official_value_unit"] = new.normalized_unit
    attrs["official_normalized_unit"] = new.normalized_unit
    indicator = normalize_official_indicator(attrs.get("official_indicator_id"))
    if indicator:
        attrs["official_indicator_id"] = indicator
    records = [NormalizationRecord(
        field_path="attributes.official_new_value", raw_value=str(raw_new),
        normalized_value=str(new.normalized_value), rule_id=new.rule_id,
    ), NormalizationRecord(
        field_path="attributes.official_value_unit", raw_value=str(raw_unit or ""),
        normalized_value=new.normalized_unit, rule_id=new.rule_id,
    )]
    raw_previous = attrs.get("official_previous_value")
    if raw_previous not in {None, ""}:
        try:
            previous = normalize_numeric_unit(raw_previous, raw_unit)
        except ValueError:
            return candidate, ["OFFICIAL_NUMERIC_UNIT_INVALID"], []
        attrs["official_previous_value_raw"] = str(raw_previous)
        attrs["official_previous_value"] = str(previous.normalized_value)
        event_type = getattr(candidate.event_type, "value", candidate.event_type)
        contradictory = (
            (event_type == "BASE_RATE_INCREASE" and new.normalized_value <= previous.normalized_value)
            or (event_type == "BASE_RATE_DECREASE" and new.normalized_value >= previous.normalized_value)
        )
        if contradictory:
            return candidate, ["OFFICIAL_VALUE_DIRECTION_CONTRADICTION"], records
    return candidate.model_copy(update={"attributes": attrs}), [], records
