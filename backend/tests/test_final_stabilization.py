"""Focused deterministic regressions for the final release stabilization."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from src.config.settings import Settings
from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import ProviderFailureDetail
from src.contracts.source_document import SourceTrustLevel, SourceType
from src.extraction.identifiers import event_candidate_id, policy_extractor_id
from src.orchestration.analysis_orchestrator import _research_summary
from src.orchestration.research_pipeline import ResearchPipelineResult
from src.providers.base import SearchHit
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.extraction.policy import (
    OpenAIPolicyExtractor,
    PolicyExtractor,
    PolicyProviderError,
)
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.policy_regulation.agent import PolicyRegulationResearchAgent
from src.storage import AuditRepository, Database, EventRepository, PolicyRepository, SourceRepository
from src.validation.policy_identity import canonicalize_policy_identity
from src.validation.policy_validator import PolicyReconciler, validate_policy_candidate
from src.validation.research_validator import ResearchEventValidator
from tests.e2e.support import load_store
from tests.research_fixtures import StaticFetcher, candidate, research_request, source_document


FIXTURE = Path(__file__).parent / "fixtures/replay/RUN-AC2AF367-58C.stabilization.v1.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _official_document(source_id: str = "SRC-POLICY", revision_id: str = "REV-POLICY"):
    fixture = _fixture()["official_policy_source"]
    body = fixture["body_text"]
    return source_document(body=body, source_id=source_id, revision_id=revision_id).model_copy(update={
        "canonical_url": f"https://www.gangnam.go.kr/policy/{source_id}",
        "publisher": "Gangnam District Office",
        "source_type": SourceType.OFFICIAL_LOCAL_GOV,
        "source_trust_level": SourceTrustLevel.OFFICIAL_TRUSTED,
        "title": fixture["title"],
    })


def _policy_payload(document, run_id: str) -> dict:
    return PolicyCandidate(
        policy_candidate_id="UNTRUSTED-PROVIDER-ID",
        research_run_id=run_id,
        policy_type="INTEREST_SUBSIDY",
        name=_fixture()["official_policy_source"]["title"],
        provider_raw="Gangnam District Office",
        purpose=["WORKING_CAPITAL"],
        region_codes=["11680"],
        limit_krw=Decimal("50000000"),
        interest_terms={"rate_discount_percentage_points": "2"},
        application_start=date(2026, 8, 1),
        application_end=date(2026, 12, 31),
        source_ids=[document.source_id],
        evidence=[EvidenceRef(
            evidence_id="EVI-POLICY",
            source_id=document.source_id,
            source_revision_id=document.revision_id,
            field_paths=["name", "policy_type", "limit_krw", "interest_terms.rate_discount_percentage_points"],
            quote=document.body_text,
            start_offset=0,
            end_offset=len(document.body_text),
        )],
    ).model_dump(mode="json", exclude={"source_validation_details"})


def _completed(output_text: str, response_id: str) -> dict:
    return {
        "id": response_id,
        "status": "completed",
        "output_text": output_text,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def test_official_policy_schema_failure_repairs_once_without_reusing_bad_output() -> None:
    document = _official_document()
    calls: list[dict] = []
    payloads = [
        _completed("not-json", "resp-invalid"),
        _completed(json.dumps({"policies": [_policy_payload(document, "RUN-AC2AF367-58C")]}), "resp-repaired"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=payloads[len(calls) - 1])

    extractor = OpenAIPolicyExtractor(
        Settings(openai_api_key="configured-test-key", max_extraction_retries=0),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = extractor.extract(document, "RUN-AC2AF367-58C", "LOW")

    assert len(calls) == 2
    assert "not-json" not in calls[1]["input"]
    assert document.body_text in calls[1]["input"]
    assert "validation_errors" in calls[1]["input"]
    assert result.diagnostic_codes == [
        "POLICY_SCHEMA_VALIDATION_FAILED",
        "POLICY_SCHEMA_REPAIR_ATTEMPTED",
        "POLICY_SCHEMA_REPAIR_SUCCEEDED",
    ]
    assert result.raw_provider_response == "not-json"
    assert len(result.policies) == 1


class _SchemaFailingPolicyExtractor(PolicyExtractor):
    def extract(self, document, research_run_id, reasoning_level):
        del research_run_id, reasoning_level
        raise PolicyProviderError(
            ProviderFailureDetail(
                stage="POLICY_EXTRACTION", provider="test", document_id=document.source_id,
                error_type="SCHEMA_VALIDATION_FAILED", error_code="SCHEMA_VALIDATION_FAILED",
            ),
            raw_provider_response="{bad-policy-json",
            validation_errors=["invalid policy DTO"],
            diagnostic_codes=[
                "POLICY_SCHEMA_VALIDATION_FAILED",
                "POLICY_SCHEMA_REPAIR_ATTEMPTED",
                "POLICY_SCHEMA_REPAIR_FAILED",
            ],
        )


def _policy_agent(tmp_path: Path, document):
    database = Database(f"sqlite:///{(tmp_path / 'policy-recovery.db').as_posix()}")
    database.migrate()
    agent = PolicyRegulationResearchAgent(
        search=FakeSearchProvider(hits=[SearchHit(url=document.canonical_url, rank=1)]),
        fetcher=StaticFetcher(document),
        extractor=FakeEventExtractor(),
        source_repo=SourceRepository(database),
        event_repo=EventRepository(database),
        audit_repo=AuditRepository(database),
        policy_extractor=_SchemaFailingPolicyExtractor(),
        policy_repo=PolicyRepository(database),
    )
    agent.seeded_hits = lambda _request: []
    return agent


def test_official_policy_schema_failure_uses_only_stated_deterministic_fallback(tmp_path: Path) -> None:
    document = _official_document()
    request = research_request("RUN-AC2AF367-58C")
    execution = _policy_agent(tmp_path, document).run(request)

    assert len(execution.policies) == 1
    fallback = execution.policies[0]
    assert fallback.policy_candidate_id == policy_extractor_id(
        request.run_id, document.source_id, document.revision_id, 1
    )
    assert fallback.application_status == "STATUS_UNCONFIRMED"
    assert "POLICY_DETERMINISTIC_FALLBACK_USED" in fallback.validation_notes
    assert execution.bundle.provider_failures == []
    codes = execution.bundle.metadata["policy_extraction_diagnostics"][0]["codes"]
    assert codes[-1] == "POLICY_DETERMINISTIC_FALLBACK_USED"
    validated = validate_policy_candidate(
        fallback, {document.source_id: document}, request.as_of_date
    )
    assert validated.application_status == "STATUS_UNCONFIRMED"


def test_policy_schema_repair_and_fallback_terminal_failure_is_explicit(tmp_path: Path) -> None:
    document = _official_document().model_copy(update={
        "title": "Official administrative notice",
        "body_text": "Official administrative notice with no stated financial support mechanism.",
    })
    execution = _policy_agent(tmp_path, document).run(research_request("RUN-AC2AF367-58C"))

    assert execution.policies == []
    assert execution.bundle.status == "PARTIAL"
    codes = execution.bundle.metadata["policy_extraction_diagnostics"][0]["codes"]
    assert "POLICY_SCHEMA_REPAIR_FAILED" in codes
    assert "POLICY_EXTRACTION_TERMINAL_FAILURE" in codes
    assert execution.policy_schema_failures[0]["raw_provider_response"] == "{bad-policy-json"


def _reconcilable_policy(document, *, name: str, supplied_id: str, limit: Decimal = Decimal("50000000")):
    evidence = EvidenceRef(
        evidence_id="EVI-" + supplied_id,
        source_id=document.source_id,
        source_revision_id=document.revision_id,
        field_paths=["name", "limit_krw"], quote=document.body_text,
        start_offset=0, end_offset=len(document.body_text),
    )
    return PolicyCandidate(
        policy_candidate_id=supplied_id,
        research_run_id="RUN-AC2AF367-58C",
        policy_type="INTEREST_SUBSIDY",
        name=name,
        provider_raw="Gangnam-gu" if supplied_id.endswith("GENERAL") else "Gangnam District Office",
        purpose=["WORKING_CAPITAL"], region_codes=["11680"], limit_krw=limit,
        interest_terms={"rate_discount_percentage_points": "2"},
        source_ids=[document.source_id], evidence=[evidence], validation_status="VALIDATED",
    )


def test_run_ac_semantic_policy_merge_prefers_year_specific_official_notice() -> None:
    fixture = _fixture()
    specific = _official_document("SRC-RUN-AC-SPECIFIC", "REV-RUN-AC-SPECIFIC")
    general = _official_document("SRC-RUN-AC-GENERAL", "REV-RUN-AC-GENERAL").model_copy(update={
        "title": fixture["general_policy_name"],
    })
    specific_policy = canonicalize_policy_identity(
        _reconcilable_policy(specific, name=specific.title, supplied_id="PC-SPECIFIC"),
        {specific.source_id: specific},
    )
    general_policy = canonicalize_policy_identity(
        _reconcilable_policy(general, name=general.title, supplied_id="PC-GENERAL"),
        {general.source_id: general},
    )
    merged = PolicyReconciler().reconcile(
        [general_policy, specific_policy],
        {specific.source_id: specific, general.source_id: general},
    )

    assert len(merged) == fixture["expected"]["merged_policy_count"]
    assert merged[0].name == specific.title
    assert merged[0].source_ids == sorted([specific.source_id, general.source_id])
    assert set(merged[0].merged_policy_candidate_ids) == {"PC-SPECIFIC", "PC-GENERAL"}


def test_materially_conflicting_policy_terms_remain_visible_but_not_recommendable() -> None:
    first = _official_document("SRC-CONFLICT-A", "REV-CONFLICT-A")
    second = _official_document("SRC-CONFLICT-B", "REV-CONFLICT-B")
    left = canonicalize_policy_identity(
        _reconcilable_policy(first, name="Gangnam SME loan interest support program", supplied_id="PC-A"),
        {first.source_id: first},
    )
    right = canonicalize_policy_identity(
        _reconcilable_policy(second, name="Gangnam SME loan interest support program", supplied_id="PC-B", limit=Decimal("60000000")),
        {second.source_id: second},
    )
    reconciled = PolicyReconciler().reconcile(
        [left, right], {first.source_id: first, second.source_id: second}
    )

    assert len(reconciled) == 2
    assert all(item.validation_status == "CONFLICTED" for item in reconciled)
    assert all("SOURCE_CONFLICT" in item.recommendation_failure_codes for item in reconciled)
    assert all(
        "limit_krw" in item.source_validation_details[-1]["conflicting_fields"]
        for item in reconciled
    )


def test_source_scoped_extraction_ids_are_stable_and_globally_unique() -> None:
    run_id = _fixture()["run_id"]
    local = event_candidate_id(run_id, "LOCAL", "SRC-ONE", "REV-ONE", 1)
    industry = event_candidate_id(run_id, "INDUSTRY", "SRC-TWO", "REV-TWO", 1)
    repeated = event_candidate_id(run_id, "LOCAL", "SRC-ONE", "REV-ONE", 1)
    first_policy = policy_extractor_id(run_id, "SRC-ONE", "REV-ONE", 1)
    second_policy = policy_extractor_id(run_id, "SRC-TWO", "REV-TWO", 1)

    assert local == repeated
    assert len({local, industry}) == 2
    assert len({first_policy, second_policy}) == 2
    assert local.startswith("EVC-RUN-AC2AF367-58C-LOCAL-SRC")
    assert first_policy.startswith("PC-RUN-AC2AF367-58C-SRC")


def test_run_ac_funnel_counts_and_outcomes_resolve_each_serialized_candidate() -> None:
    fixture = _fixture()
    request = research_request(fixture["run_id"])
    document = source_document()
    accepted = candidate(document, candidate_id="EVC-ACCEPT").model_copy(update={"research_run_id": request.run_id})
    rejected = candidate(document, candidate_id="EVC-REJECT", start="2027-08-01", end="2027-09-01").model_copy(update={"research_run_id": request.run_id})
    validator = ResearchEventValidator()
    accepted_outcome = validator.validate(accepted, {document.source_id: document}, request)
    rejected_outcome = validator.validate(rejected, {document.source_id: document}, request)
    summary = _research_summary(
        ResearchPipelineResult(
            run_id=request.run_id,
            accepted_events=[accepted_outcome.event],
            rejected_events=[rejected_outcome],
        ),
        ResearchPipelineResult(run_id=request.run_id),
        [],
        load_store(),
    )

    assert summary.funnel.candidate_count == fixture["expected"]["event_candidate_count"]
    assert summary.funnel.accepted_event_count == fixture["expected"]["accepted_candidate_count"]
    assert summary.funnel.rejected_candidate_count == fixture["expected"]["rejected_candidate_count"]
    assert {item.candidate_id for item in summary.event_pipeline_outcomes} == {
        "EVC-ACCEPT", "EVC-REJECT",
    }


def test_duplicate_candidate_ids_fail_the_serialized_funnel_contract() -> None:
    request = research_request("RUN-DUPLICATE-ID")
    document = source_document()
    item = candidate(document, candidate_id="EVC-DUP", start="2027-08-01", end="2027-09-01").model_copy(update={"research_run_id": request.run_id})
    rejected = ResearchEventValidator().validate(item, {document.source_id: document}, request)

    with pytest.raises(ValueError, match="duplicate rejected event candidate IDs"):
        _research_summary(
            ResearchPipelineResult(run_id=request.run_id, rejected_events=[rejected, rejected]),
            ResearchPipelineResult(run_id=request.run_id), [], load_store(),
        )
