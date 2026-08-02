from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from src.config.settings import Settings
from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import ProviderFailureDetail
from src.contracts.source_document import AccessStatus, SourceDocument, SourceType
from src.providers.base import DocumentFetcher, SearchHit
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.extraction.policy import (
    OpenAIPolicyExtractor,
    PolicyExtractionResult,
    PolicyExtractor,
    PolicyProviderError,
)
from src.providers.extraction.policy_dto import provider_policy_schema
from src.providers.search.fake import FakeSearchProvider
from src.research_agents.policy_regulation.agent import PolicyRegulationResearchAgent
from src.storage import AuditRepository, Database, EventRepository, PolicyRepository, SourceRepository
from tests.research_fixtures import research_request


BODY = (
    "2026년 강남구 중소기업·소상공인 대출이자 지원사업 안내. "
    "강남구 소재 중소기업과 소상공인은 협약은행 대출 이자 지원을 신청할 수 있습니다. "
    "세부 자격과 접수 가능 여부는 강남구청 공고 원문에서 확인해야 합니다. " * 4
)


def document(source_id: str = "SRC-GANGNAM") -> SourceDocument:
    return SourceDocument(
        source_id=source_id,
        canonical_url=f"https://www.gangnam.go.kr/board/B_000001/{source_id}/view.do",
        publisher="강남구청",
        source_type=SourceType.OFFICIAL_LOCAL_GOV,
        published_at=datetime(2026, 2, 1, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
        title="2026년 강남구 중소기업·소상공인 대출이자 지원사업 안내",
        body_text=BODY,
        body_sha256=hashlib.sha256(BODY.encode()).hexdigest(),
        access_status=AccessStatus.OK,
        http_status=200,
        content_type="text/html",
        revision_id=f"REV-{source_id}",
    )


def policy_payload(doc: SourceDocument, run_id: str = "RES-POLICY") -> dict:
    quote = BODY[:50]
    return PolicyCandidate(
        policy_candidate_id="POL-GANGNAM-2026",
        research_run_id=run_id,
        policy_type="INTEREST_SUBSIDY",
        name="2026년 강남구 중소기업·소상공인 대출이자 지원사업",
        provider_raw="강남구청",
        purpose=["WORKING_CAPITAL"],
        region_codes=["11680"],
        limit_krw=Decimal("50000000"),
        interest_terms={"rate_discount_percentage_points": "2"},
        budget_status="UNKNOWN",
        source_ids=[doc.source_id],
        evidence=[EvidenceRef(
            evidence_id="EVI-GANGNAM",
            source_id=doc.source_id,
            source_revision_id=doc.revision_id,
            field_paths=["name", "policy_type"],
            quote=quote,
            start_offset=0,
            end_offset=len(quote),
        )],
    ).model_dump(mode="json", exclude={"source_validation_details"})


def extractor_for(payload: dict, status: int = 200, **setting_overrides) -> OpenAIPolicyExtractor:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, headers={"x-request-id": "req_sanitized"})

    settings = Settings(
        openai_api_key="configured-test-key",
        max_extraction_retries=setting_overrides.get("max_extraction_retries", 0),
    )
    return OpenAIPolicyExtractor(settings, httpx.Client(transport=httpx.MockTransport(handler)))


def test_production_policy_schema_matches_strict_provider_contract() -> None:
    schema = provider_policy_schema()
    encoded = json.dumps(schema)
    assert '"default"' not in encoded
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False

    def check(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                assert node["additionalProperties"] is False
                assert node["required"] == list(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)


def test_valid_policy_response_returns_typed_candidate() -> None:
    doc = document()
    response_payload = policy_payload(doc)
    response_payload["policy_type"] = "loan_interest_subsidy"
    response = {
        "id": "resp_policy",
        "status": "completed",
        "output_text": json.dumps({"policies": [response_payload]}, ensure_ascii=False),
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    result = extractor_for(response).extract(doc, "RES-POLICY", "LOW")
    assert result.policies[0].policy_type == "INTEREST_SUBSIDY"
    assert result.request_id == "resp_policy"


def test_http_400_is_sanitized_and_not_retried() -> None:
    doc = document()
    response = {
        "error": {
            "message": f"invalid schema; leaked body={BODY}; key=secret-value",
            "type": "invalid_request_error",
            "code": "invalid_json_schema",
            "param": "text.format.schema",
        }
    }
    with pytest.raises(PolicyProviderError) as caught:
        extractor_for(response, 400).extract(doc, "RES-POLICY", "LOW")
    detail = caught.value.detail
    assert detail.http_status == 400
    assert detail.error_type == "invalid_request_error"
    assert detail.error_code == "POLICY_SCHEMA_REJECTED_BY_PROVIDER"
    assert detail.parameter == "text.format.schema"
    assert detail.request_id == "req_sanitized"
    assert not detail.retryable
    assert "secret-value" not in str(detail.model_dump())
    assert BODY not in str(detail.model_dump())


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]}, "REFUSAL"),
        ({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, "INCOMPLETE_MAX_OUTPUT_TOKENS"),
        ({"status": "completed", "output_text": "not-json"}, "SCHEMA_VALIDATION_FAILED"),
    ],
)
def test_refusal_incomplete_and_malformed_are_typed(payload: dict, code: str) -> None:
    with pytest.raises(PolicyProviderError) as caught:
        extractor_for(payload).extract(document(), "RES-POLICY", "LOW")
    assert caught.value.detail.error_code == code


class MappingFetcher(DocumentFetcher):
    def __init__(self, documents: dict[str, SourceDocument]):
        self.documents = documents

    def fetch(self, hit: SearchHit) -> SourceDocument:
        return self.documents[hit.url]


class PartialPolicyExtractor(PolicyExtractor):
    def __init__(self, successful: SourceDocument, policy: PolicyCandidate):
        self.successful = successful
        self.policy = policy

    def extract(self, document, research_run_id, reasoning_level):
        if document.source_id != self.successful.source_id:
            raise PolicyProviderError(ProviderFailureDetail(
                stage="POLICY_EXTRACTION",
                provider="openai",
                model="test-model",
                document_id=document.source_id,
                http_status=400,
                error_type="invalid_request_error",
                error_code="invalid_json_schema",
            ))
        return PolicyExtractionResult(
            "resp-success", "openai", "test-model", [self.policy]
        )


def test_one_failed_policy_document_preserves_successful_document(tmp_path: Path) -> None:
    failed = document("SRC-FAILED")
    successful_body = BODY + " 접수기간은 예산 소진 시까지이며 상세 공고를 확인하십시오."
    successful = document("SRC-SUCCESS").model_copy(update={
        "body_text": successful_body,
        "body_sha256": hashlib.sha256(successful_body.encode()).hexdigest(),
    })
    policy = PolicyCandidate.model_validate(policy_payload(successful, "RES-POL-PARTIAL"))
    db = Database(f"sqlite:///{(tmp_path / 'policy.db').as_posix()}")
    db.migrate()
    sources = SourceRepository(db)
    events = EventRepository(db)
    policies = PolicyRepository(db)
    audit = AuditRepository(db)
    agent = PolicyRegulationResearchAgent(
        search=FakeSearchProvider(hits=[
            SearchHit(url=failed.canonical_url, rank=1),
            SearchHit(url=successful.canonical_url, rank=2),
        ]),
        fetcher=MappingFetcher({
            failed.canonical_url: failed,
            successful.canonical_url: successful,
        }),
        extractor=FakeEventExtractor(),
        source_repo=sources,
        event_repo=events,
        audit_repo=audit,
        policy_extractor=PartialPolicyExtractor(successful, policy),
        policy_repo=policies,
    )
    # This test verifies partial provider failure handling, not live-source fallback.
    # Keep its mapping fetcher intentionally scoped to the two fixture documents.
    agent.seeded_hits = lambda _request: []
    execution = agent.run(research_request("RES-POL-PARTIAL"))
    assert [item.policy_candidate_id for item in execution.policies] == ["PC-RES-POL-PARTIAL-SRC78491FE11D-001"]
    assert execution.policies[0].extractor_policy_candidate_id == execution.policies[0].policy_candidate_id
    assert execution.bundle.status == "PARTIAL"
    assert len(execution.bundle.provider_failures) == 1
    assert execution.bundle.provider_failures[0].document_id == failed.source_id
    assert not {
        "NO_EVENT_FOUND", "NO_DISCRETE_EVENT", "EXTRACTION_NO_CANDIDATES"
    }.intersection(execution.bundle.no_result_reasons)
