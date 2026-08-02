"""Generate the deterministic, sanitized Phase 5 A/B/C replay bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

from src.contracts.event_candidate import (
    EvidenceRef,
    EventImpact,
    ExtractedEventCandidate,
    ExtractionMetadata,
    LocationRaw,
    TemporalRaw,
)
from src.contracts.research import ResearchRequest, StoreLocation
from src.contracts.source_document import AccessStatus, SourceDocument, SourceType
from src.validation.reconciler import assign_cause_groups
from src.validation.research_validator import ResearchEventValidator


RUN_ID = "ABC-C-REPLAY"
BODY = (
    "Seoul City announced a partial pedestrian-path closure near the recorded "
    "Gangnam cafe from 2026-08-01 through 2026-09-15."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_bundle(repo_root: Path) -> dict[str, object]:
    body_hash = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    document = SourceDocument(
        source_id="SRC-RECORDED-SEOUL-ACCESS",
        canonical_url="https://www.seoul.go.kr/recorded-contract-not-live",
        publisher="Seoul City",
        source_type=SourceType.OFFICIAL_LOCAL_GOV,
        published_at=datetime(2026, 7, 20, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
        title="Recorded pedestrian access notice",
        raw_content_sha256=body_hash,
        body_text=BODY,
        body_sha256=body_hash,
        access_status=AccessStatus.OK,
        http_status=200,
        content_type="text/plain",
        revision_id="REV-RECORDED-SEOUL-ACCESS-1",
    )
    evidence = EvidenceRef(
        evidence_id="EVD-RECORDED-SEOUL-ACCESS-1",
        source_id=document.source_id,
        source_revision_id=document.revision_id,
        field_paths=[
            "event_type",
            "temporal.start_raw",
            "temporal.end_raw",
            "impacts[0].mechanism",
        ],
        quote=BODY,
        start_offset=0,
        end_offset=len(BODY),
    )
    candidate = ExtractedEventCandidate(
        candidate_id="EVC-RECORDED-SEOUL-ACCESS-1",
        research_run_id=RUN_ID,
        domain="LOCAL",
        event_family="ACCESSIBILITY",
        event_type="PEDESTRIAN_PARTIAL_CLOSURE",
        title="Partial pedestrian path closure",
        actor_org_raw="Seoul City",
        target_subject_raw="Recorded Gangnam cafe access",
        temporal=TemporalRaw(start_raw="2026-08-01", end_raw="2026-09-15"),
        location=LocationRaw(
            address_raw="Recorded Gangnam cafe",
            latitude=37.5007,
            longitude=127.0365,
        ),
        affected_industries_raw=["FNB"],
        impacts=[
            EventImpact(
                axis="REVENUE_DEMAND",
                direction="DECREASE",
                mechanism="PEDESTRIAN_ACCESS_RESTRICTION",
                evidence_ids=[evidence.evidence_id],
            )
        ],
        attributes={"closure_scope": "PARTIAL"},
        evidence=[evidence],
        extraction_metadata=ExtractionMetadata(
            model="recorded-contract",
            prompt_version="local_event_extract.v1",
        ),
    )
    request = ResearchRequest(
        run_id=RUN_ID,
        as_of_date=date(2026, 7, 31),
        forecast_start=date(2026, 8, 1),
        forecast_end=date(2027, 1, 31),
        store_profile_snapshot_id="SNAPSHOT-PRIMARY-CAFE",
        business_type_code="FNB_CAFE",
        ingredient_categories=["COFFEE_BEAN"],
        store_location=StoreLocation(
            address="Recorded Gangnam cafe",
            latitude=37.5007,
            longitude=127.0365,
            administrative_area="Seoul Gangnam-gu",
        ),
        administrative_area_codes=["11680"],
        search_radius_m=1500,
        official_indicator_snapshot_ids=[
            "USD_KRW",
            "BASE_RATE",
            "FOOD_PRICE_INDEX",
            "IMPORT_UNIT_PRICE_HS090111",
        ],
    )
    outcome = ResearchEventValidator().validate(
        candidate, {document.source_id: document}, request
    )
    if outcome.status != "ACCEPTED" or outcome.event is None:
        raise RuntimeError(f"recorded replay event did not validate: {outcome.failure_codes}")
    accepted_event = assign_cause_groups(
        [outcome.event], request.official_indicator_snapshot_ids
    )[0]
    store_path = repo_root / "tests/fixtures/stores/cafe_gangnam_24m.json"
    official_path = repo_root / "tests/fixtures/official/offline_official_observations.json"
    return {
        "schema_version": "integrated_replay_bundle.v1",
        "provenance": "RECORDED_CONTRACT_NOT_LIVE",
        "capture_status": "SANITIZED_DETERMINISTIC_FALLBACK",
        "run_id": RUN_ID,
        "store_fixture": {
            "path": store_path.relative_to(repo_root).as_posix(),
            "sha256": _sha256(store_path),
            "coordinate_overrides": {
                "latitude": "37.5007",
                "longitude": "127.0365",
            },
        },
        "official_fixture": {
            "path": official_path.relative_to(repo_root).as_posix(),
            "sha256": _sha256(official_path),
        },
        "request": request.model_dump(mode="json"),
        "source_documents": [document.model_dump(mode="json")],
        "event_candidates": [candidate.model_dump(mode="json")],
        "accepted_events": [accepted_event.model_dump(mode="json")],
        "reference_findings": [
            {
                "finding_id": "FND-GANGNAM-POLICY-REFERENCE",
                "status": "REFERENCE_ONLY",
                "title": "2026년 강남구 중소기업·소상공인 대출이자 지원사업 안내",
                "source_url": "https://www.gangnam.go.kr/board/B_000001/1076295/view.do?mid=ID05_040101",
                "reason_code": "STRICT_EVENT_TEMPORAL_AND_IMPACT_EVIDENCE_MISSING",
                "financial_signal_eligible": False,
            }
        ],
        "rejected_candidates": [
            {
                "candidate_id": "EC-001",
                "title": "Cocoa international price increase",
                "source_url": "https://mafra.go.kr/bbs/home/793/584779/download.do",
                "raw_start_date": "25.1.16",
                "failure_codes": ["DATE_PARSE_FAILED"],
                "signal_enabled": False,
                "provenance": "RUN-7FABA7E0-B71_DIAGNOSTIC_EVIDENCE",
            }
        ],
        "policy_candidates": [
            {
                "policy_candidate_id": "POL-GANGNAM-INTEREST-2026",
                "name": "2026년 강남구 중소기업·소상공인 대출이자 지원사업",
                "provider": "강남구청",
                "source_url": "https://www.gangnam.go.kr/board/B_000001/1076295/view.do?mid=ID05_040101",
                "status": "REFERENCE_ONLY_RECONFIRM_LIVE",
            }
        ],
        "demonstration_layers": {
            "applied_signal": {
                "signal_id": "SIG-RECORDED-ACCESS-2026-08",
                "event_id": accepted_event.event_id,
                "financial_signal_eligible": True,
            },
            "reference_findings_change_finance": False,
            "rejected_candidates_change_finance": False,
            "ai_risk_ending_cash_delta_krw": -2400000,
        },
        "versions": {
            "event_registry_version": request.event_registry_version,
            "source_policy_version": request.source_policy_version,
            "coefficient_version": "coefficients.v1",
            "official_feature_version": "official_features.v2.decayed_capped",
            "financial_calculation_version": "financial_calculation.v2",
        },
        "limitations": [
            "This fixture is a deterministic contract recording, not a successful live LLM capture.",
            "A live capture may replace it only after Gemini search and OpenAI extraction both complete.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/replay/controlled_abc_replay.v1.json"),
    )
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else repo_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_bundle(repo_root), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
