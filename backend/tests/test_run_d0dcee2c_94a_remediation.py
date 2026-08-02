from datetime import UTC, date, datetime
from decimal import Decimal

from src.contracts.canonical_event import CanonicalEvent, CanonicalLocation, NormalizationRecord
from src.contracts.event_candidate import EventImpact, EvidenceRef
from src.contracts.official import (
    CanonicalObservation, ObservationFrequency, OfficialDataBundle, OfficialDataStatus,
)
from src.finance.monthly_scenario import run_monthly_financial_scenario
from src.forecasting.official_features import OfficialFeatureBuilder
from src.ingestion.official_api.map_api import MapApiAdapter
from src.normalization.geo_normalizer import FakeGeocoder, GeoCandidate
from src.orchestration.analysis_orchestrator import _research_summary
from src.orchestration.research_pipeline import ResearchPipelineResult
from src.validation.policy_validator import validate_policy_candidate
from src.validation.research_validator import ResearchEventValidator, ValidationOutcome
from tests.e2e.support import load_store
from tests.research_fixtures import candidate, research_request, source_document
from tests.contract.test_financial_golden_store import _baseline, _neutral
from tests.test_policy_pipeline_integration import run_policy_pipeline
from src.contracts.source_document import SourceType


def observation(day: date, value: str, observation_id: str) -> CanonicalObservation:
    released = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return CanonicalObservation(
        observation_id=observation_id,
        indicator_id="BASE_RATE",
        value=Decimal(value),
        unit="PERCENT",
        frequency=ObservationFrequency.MONTHLY,
        observed_at=day,
        released_at=released,
        available_at=released,
        source_id=f"SRC-{observation_id}",
        source_revision_id=f"REV-{observation_id}",
        vintage_id=f"VIN-{observation_id}",
    )


def rate_event() -> CanonicalEvent:
    quote = "The official base rate increased from 2.50% to 2.75% on July 16."
    evidence = EvidenceRef(
        evidence_id="EVI-RATE",
        source_id="SRC-RATE",
        source_revision_id="REV-RATE",
        field_paths=[
            "event_type", "temporal.start_raw", "impacts[0]",
            "attributes.official_indicator_id", "attributes.official_new_value",
            "attributes.official_value_unit",
        ],
        quote=quote,
        start_offset=0,
        end_offset=len(quote),
    )
    return CanonicalEvent(
        event_id="EVT-RATE-JUL16",
        candidate_ids=["EVC-RATE-JUL16"],
        research_run_id="RUN-D0DCEE2C-94A",
        domain="MACRO",
        event_family="MONETARY_POLICY",
        event_type="BASE_RATE_INCREASE",
        title="Official base-rate increase",
        start_date=date(2026, 7, 16),
        end_date=date(2027, 1, 31),
        location=CanonicalLocation(),
        affected_industry_codes=["FNB"],
        impacts=[EventImpact(
            axis="INTEREST_COST", direction="INCREASE",
            mechanism="POLICY_RATE_TRANSMISSION", evidence_ids=[evidence.evidence_id],
        )],
        attributes={
            "official_indicator_id": "BASE_RATE",
            "official_previous_value": "2.50",
            "official_new_value": "2.75",
            "official_value_unit": "PERCENT",
        },
        evidence=[evidence],
        source_ids=["SRC-RATE"],
        source_revision_ids=["REV-RATE"],
        source_tier="OFFICIAL_PRIMARY",
        validation_status="ACCEPTED",
        normalization_records=[NormalizationRecord(
            field_path="temporal.start_raw", raw_value="2026-07-16",
            normalized_value="2026-07-16", rule_id="ISO_DATE_V1",
        )],
        fingerprint="rate-jul16",
        signal_enabled=False,
        signal_eligibility_reason="Official indicator bridge prevents double counting.",
    )


def official_bundle(*observations: CanonicalObservation) -> OfficialDataBundle:
    return OfficialDataBundle(
        snapshot_id="OFF-RATE-BRIDGE",
        as_of_date=date(2026, 7, 30),
        observations=list(observations),
        status=OfficialDataStatus.COMPLETED,
    )


def test_tiered_keyword_resolution_ranks_area_context_and_store_proximity() -> None:
    payload = {"documents": [
        {
            "id": "far", "place_name": "Central Road", "address_name": "Busan Jung-gu",
            "road_address_name": "Busan Jung-gu Central Road", "category_name": "road",
            "x": "129.032", "y": "35.106",
        },
        {
            "id": "near", "place_name": "Central Road", "address_name": "Seoul Gangnam-gu",
            "road_address_name": "Seoul Gangnam-gu Central Road", "category_name": "road segment",
            "x": "127.0276", "y": "37.4979",
        },
    ]}
    latitude, longitude, metadata = MapApiAdapter().select_kakao_keyword_candidate(
        "Central Road",
        payload,
        store_latitude=37.498,
        store_longitude=127.028,
        administrative_area_codes=["Seoul Gangnam-gu"],
        source_context="Closure on Central Road in Seoul Gangnam-gu",
    )
    assert (str(latitude), str(longitude)) == ("37.4979", "127.0276")
    assert metadata["match_type"] == "LANDMARK_ROAD_SEGMENT"
    assert metadata["candidate_count"] == 2
    assert metadata["distance_meters"] < 100


def test_administrative_area_fallback_is_explicit(monkeypatch) -> None:
    import json
    from urllib.parse import parse_qs, urlsplit

    class Response:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    monkeypatch.setenv("KAKAO_REST_API_KEY", "configured-test-key")

    def opener(request, **_kwargs):
        query = parse_qs(urlsplit(request.full_url).query).get("query", [""])[0]
        if "Seoul Gangnam-gu" in query:
            return Response({"documents": [{
                "id": "admin", "place_name": "Gangnam District Office",
                "address_name": "Seoul Gangnam-gu", "road_address_name": "Seoul Gangnam-gu",
                "category_name": "public administration", "x": "127.0473", "y": "37.5172",
            }]})
        return Response({"documents": []})

    latitude, longitude, metadata = MapApiAdapter(opener=opener).resolve_location(
        "Unresolved neighborhood label",
        store_latitude=37.50,
        store_longitude=127.03,
        administrative_area_codes=["Seoul Gangnam-gu"],
        allow_administrative_fallback=True,
    )
    assert latitude is not None and longitude is not None
    assert metadata["match_type"] == "ADMINISTRATIVE_AREA_FALLBACK"
    assert metadata["precision"] == "REPRESENTATIVE_AREA_POINT"


def test_geocoder_provider_failure_is_not_reported_as_not_found() -> None:
    document = source_document()
    item = candidate(document)
    item.location.latitude = None
    item.location.longitude = None
    geocoder = FakeGeocoder({}, statuses={"Gangnam Road": "PROVIDER_ERROR"}, metadata={
        "Gangnam Road": {"provider": "KAKAO", "reason": "KAKAO_TIMEOUT"},
    })
    outcome = ResearchEventValidator(geocoder=geocoder).validate(
        item, {document.source_id: document}, research_request()
    )
    assert "GEO_PROVIDER_ERROR" in outcome.failure_codes
    assert "GEO_NOT_FOUND" not in outcome.failure_codes
    assert outcome.validation_metadata["provider"] == "KAKAO"


def test_resolved_landmark_then_excluded_by_distance_retains_metadata() -> None:
    document = source_document()
    item = candidate(document)
    item.location.latitude = None
    item.location.longitude = None
    geocoder = FakeGeocoder({"Gangnam Road": [GeoCandidate(
        address="Gangnam Road representative point", latitude=37.60, longitude=127.10,
        provider="KAKAO", match_method="LANDMARK_ROAD_SEGMENT",
    )]})
    outcome = ResearchEventValidator(geocoder=geocoder).validate(
        item, {document.source_id: document}, research_request()
    )
    assert "OUTSIDE_SEARCH_RADIUS" in outcome.failure_codes
    assert outcome.validation_metadata["distance_meters"] > 1500
    assert outcome.validation_metadata["configured_radius_meters"] == 1500
    assert outcome.lifecycle_stages[-1] == "EXCLUDED_BY_DISTANCE"


def test_distance_boundary_excludes_only_beyond_1500_meters() -> None:
    import math

    document = source_document()
    request = research_request()
    store_lat = request.store_location.latitude
    store_lon = request.store_location.longitude
    assert store_lat is not None and store_lon is not None

    def at_distance(distance_meters: float):
        item = candidate(document)
        item.location.latitude = store_lat + math.degrees(distance_meters / 6_371_000.0)
        item.location.longitude = store_lon
        return ResearchEventValidator().validate(item, {document.source_id: document}, request)

    inside = at_distance(1499)
    outside = at_distance(1501)
    assert "OUTSIDE_SEARCH_RADIUS" not in inside.failure_codes
    assert "OUTSIDE_SEARCH_RADIUS" in outside.failure_codes


def test_newer_official_rate_event_bridges_and_expires_when_series_catches_up() -> None:
    stale = official_bundle(
        observation(date(2026, 5, 31), "2.50", "OBS-MAY"),
        observation(date(2026, 6, 30), "2.50", "OBS-JUN"),
    )
    bridged = OfficialFeatureBuilder().build(
        stale, date(2026, 8, 1), 2, official_events=[rate_event()]
    )
    assert bridged.event_overrides[0].status == "APPLIED"
    override_id = bridged.event_overrides[0].synthetic_observation_id
    assert override_id in bridged.months[0].source_observation_ids
    assert bridged.months[0].interest_rate_delta == Decimal("0.0025")

    caught_up = official_bundle(
        observation(date(2026, 6, 30), "2.50", "OBS-JUN"),
        observation(date(2026, 7, 16), "2.75", "OBS-JUL16"),
    )
    current = OfficialFeatureBuilder().build(
        caught_up, date(2026, 8, 1), 1, official_events=[rate_event()]
    )
    assert current.event_overrides[0].status == "EXPIRED"
    assert current.event_overrides[0].reason_code == "OFFICIAL_SERIES_CAUGHT_UP"
    assert all(not value.startswith("OVR-") for value in current.months[0].source_observation_ids)


def test_zero_declared_variable_debt_share_blocks_official_rate_impact() -> None:
    store = load_store().model_copy(deep=True)
    store.cost_exposures.variable_rate_debt_share = Decimal("0")
    baseline = _baseline(store)
    neutral = _neutral()
    plain = run_monthly_financial_scenario(store, baseline, neutral)
    stale = official_bundle(
        observation(date(2026, 5, 31), "2.50", "OBS-MAY"),
        observation(date(2026, 6, 30), "2.50", "OBS-JUN"),
    )
    features = OfficialFeatureBuilder().build(
        stale, date(2026, 8, 1), 1, official_events=[rate_event()]
    )
    bridged = run_monthly_financial_scenario(
        store, baseline, neutral, official_features=features
    )
    assert bridged.monthly_cash_flows[0].interest_payment_krw == plain.monthly_cash_flows[0].interest_payment_krw


def test_policy_offset_and_revision_repair_is_auditable() -> None:
    document = source_document()
    result = run_policy_pipeline  # keeps import coverage explicit for the integrated policy path
    del result
    from src.contracts.policy_candidate import PolicyCandidate
    evidence = EvidenceRef(
        evidence_id="PE-REPAIR", source_id=document.source_id,
        source_revision_id="OLD-REVISION", field_paths=["name"],
        quote=document.body_text, start_offset=1, end_offset=len(document.body_text),
    )
    policy = PolicyCandidate(
        policy_candidate_id="POL-REPAIR", research_run_id="RUN-POLICY",
        policy_type="LOAN_SUPPORT", name="Working capital", provider_raw="Seoul City",
        source_ids=[document.source_id], evidence=[evidence],
    )
    validated = validate_policy_candidate(policy, {document.source_id: document}, date(2026, 7, 30))
    assert validated.validation_status == "VALIDATED"
    assert set(validated.validation_notes) == {
        "POLICY_EVIDENCE_OFFSET_REPAIRED", "POLICY_REVISION_REBOUND_TO_STORED_SOURCE",
    }
    assert validated.evidence[0].source_revision_id == document.revision_id
    assert validated.evidence[0].start_offset == 0


def test_pipeline_status_explains_distance_exclusion() -> None:
    document = source_document()
    item = candidate(document, lat=35.0, lon=129.0)
    outcome = ResearchEventValidator().validate(item, {document.source_id: document}, research_request())
    summary = _research_summary(
        ResearchPipelineResult(run_id="RUN", rejected_events=[outcome]),
        ResearchPipelineResult(run_id="RUN"),
        [],
        load_store(),
    )
    pipeline = summary.event_pipeline_outcomes[0]
    assert pipeline.terminal_status == "EXCLUDED_BY_DISTANCE"
    assert pipeline.primary_exclusion_reason == "OUTSIDE_SEARCH_RADIUS"
    assert pipeline.store_distance_meters > pipeline.configured_radius_meters
