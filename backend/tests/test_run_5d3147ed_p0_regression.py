"""Deterministic P0 regression coverage for RUN-5D3147ED-912."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib

import httpx

from src.config.settings import Settings
from src.contracts.event_candidate import (
    EvidenceRef, EventImpact, ExtractedEventCandidate, ExtractionMetadata, LocationRaw,
    TemporalRaw,
)
from src.contracts.research import ResearchRequest, StoreLocation
from src.contracts.source_document import AccessStatus, SourceDocument, SourceType
from src.forecasting.official_features import OfficialFeatureBuilder
from src.ingestion.official_api.map_api import MapApiAdapter
from src.normalization.venue_normalizer import administrative_area_names, venue_search_forms
from src.providers.base import SearchHit
from src.source_snapshot.bok import assess_bok_monetary_policy_content
from src.source_snapshot.fetcher import HttpDocumentFetcher
from src.validation.research_validator import ResearchEventValidator


def _source(body: str) -> SourceDocument:
    return SourceDocument(
        source_id="SRC-BOK-DECISION",
        canonical_url="https://www.bok.or.kr/portal/bbs/B0000245/view.do?nttId=1",
        publisher="Bank of Korea",
        source_type=SourceType.OFFICIAL_PRIMARY,
        published_at=datetime(2026, 7, 16, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
        title="Monetary Policy Decision",
        body_text=body,
        body_sha256=hashlib.sha256(body.encode()).hexdigest(),
        access_status=AccessStatus.OK,
        http_status=200,
        content_type="text/plain",
        revision_id="REV-BOK-DECISION",
    )


def _request() -> ResearchRequest:
    return ResearchRequest(
        run_id="RUN-5D3147ED-912",
        as_of_date=date(2026, 7, 30),
        forecast_start=date(2026, 8, 1),
        forecast_end=date(2026, 9, 30),
        store_profile_snapshot_id="STORE-SNAPSHOT-1",
        business_type_code="FNB_CAFE",
        store_location=StoreLocation(address="Seoul Gangnam-gu", latitude=37.5, longitude=127.03),
        administrative_area_codes=["11680"],
    )


def test_bok_incomplete_detail_recovers_attachment_and_preserves_lineage(tmp_path) -> None:
    detail_url = "https://www.bok.or.kr/portal/bbs/B0000245/view.do?nttId=1"
    attachment_url = "https://www.bok.or.kr/portal/decision-20260716.txt"
    html = b"""
        <html><head><title>Decision list</title></head><body>
          <nav>Menu Login Related notices</nav>
          <a href='/portal/decision-20260716.txt'>Official decision text</a>
        </body></html>
    """
    decision = (
        "The Monetary Policy Board decided on July 16, 2026 to raise the Base Rate "
        "from 2.50% to 2.75%, effective immediately."
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == detail_url:
            return httpx.Response(200, headers={"content-type": "text/html"}, content=html)
        if str(request.url) == attachment_url:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=decision)
        return httpx.Response(404)

    fetcher = HttpDocumentFetcher(
        Settings(snapshot_dir=tmp_path / "snapshots"), httpx.MockTransport(handler)
    )
    documents = fetcher.fetch_with_attachments(SearchHit(
        url=detail_url, rank=1, allowed_domains=["bok.or.kr"],
    ))

    parent, attachment = documents
    assert parent.attachment_urls == [attachment_url]
    assert attachment.parent_source_id == parent.source_id
    assert attachment.raw_content_sha256 == hashlib.sha256(decision).hexdigest()
    assert attachment.revision_id
    assessment = assess_bok_monetary_policy_content(attachment)
    assert assessment.usable
    assert not assessment.reason_codes


def test_bok_decision_evidence_accepts_rate_event_and_drives_official_bridge() -> None:
    body = (
        "The Monetary Policy Board decided on July 16, 2026 to raise the Base Rate "
        "from 2.50% to 2.75%, effective immediately."
    )
    document = _source(body)
    evidence = EvidenceRef(
        evidence_id="EVI-BOK-RATE", source_id=document.source_id,
        source_revision_id=document.revision_id,
        field_paths=[
            "event_type", "temporal.start_raw", "impacts[0]",
            "attributes.official_indicator_id", "attributes.official_previous_value",
            "attributes.official_new_value", "attributes.official_value_unit",
        ],
        quote=body, start_offset=0, end_offset=len(body),
    )
    candidate = ExtractedEventCandidate(
        candidate_id="EVC-BOK-RATE", research_run_id="RUN-5D3147ED-912",
        domain="MACRO", event_family="MONETARY_POLICY", event_type="BASE_RATE_INCREASE",
        title="July 2026 base-rate decision", actor_org_raw="Bank of Korea",
        temporal=TemporalRaw(start_raw="2026-07-16"), location=LocationRaw(),
        affected_industries_raw=["FNB"],
        impacts=[EventImpact(
            axis="INTEREST_COST", direction="INCREASE", mechanism="POLICY_RATE_TRANSMISSION",
            evidence_ids=[evidence.evidence_id],
        )],
        attributes={
            "official_indicator_id": "BASE_RATE", "official_previous_value": "2.50",
            "official_new_value": "2.75", "official_value_unit": "PERCENT",
        },
        evidence=[evidence], extraction_metadata=ExtractionMetadata(
            model="fixture", prompt_version="run_5d3147ed_fixture.v1",
        ),
    )
    outcome = ResearchEventValidator().validate(candidate, {document.source_id: document}, _request())

    assert outcome.status == "ACCEPTED"
    assert outcome.event is not None
    assert outcome.event.event_type == "BASE_RATE_INCREASE"
    assert outcome.event.source_tier == "OFFICIAL_PRIMARY"

    from tests.test_run_d0dcee2c_94a_remediation import official_bundle, observation

    features = OfficialFeatureBuilder().build(
        official_bundle(observation(date(2026, 6, 30), "2.50", "OBS-JUN")),
        date(2026, 8, 1), 1, official_events=[outcome.event],
    )
    assert features.event_overrides[0].status == "APPLIED"
    assert features.months[0].interest_rate_delta == Decimal("0.0025")


def test_korean_compound_venue_queries_use_administrative_name_and_reject_commercial_match() -> None:
    location = "\uac15\ub0a8\uc5ed \uad11\uc7a5 \ubc0f \uc8fc\uc694 \uad00\uad11\uba85\uc18c"
    forms = venue_search_forms(location, administrative_area_codes=["11680"])
    assert forms[0] == "\uac15\ub0a8\uc5ed \uad11\uc7a5"
    assert "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uac15\ub0a8\uad6c" in administrative_area_names(["11680"])

    payload = {"documents": [
        {
            "id": "cafe-nearby", "place_name": "\uac15\ub0a8\uc5ed \uce74\ud398", "address_name": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uac15\ub0a8\uad6c",
            "category_name": "\uc74c\uc2dd\uc810 > \uce74\ud398", "x": "127.030", "y": "37.500",
        },
        {
            "id": "plaza", "place_name": "\uac15\ub0a8\uc5ed \uad11\uc7a5", "address_name": "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uac15\ub0a8\uad6c",
            "category_name": "\uad00\uad11\uba85\uc18c > \uad11\uc7a5", "x": "127.035", "y": "37.505",
        },
    ]}
    latitude, longitude, metadata = MapApiAdapter().select_kakao_keyword_candidate(
        forms[0], payload, store_latitude=37.5, store_longitude=127.03,
        administrative_area_codes=["11680"], source_context="\uc9c0\uc5ed \ud589\uc0ac",
    )
    assert (str(latitude), str(longitude)) == ("37.505", "127.035")
    assert metadata["administrative_area_names"] == ["\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uac15\ub0a8\uad6c"]
    assert metadata["ranked_candidates"][0]["id"] == "plaza"
    assert metadata["rejected_candidates"][0]["reason"] == "COMMERCIAL_CATEGORY"
