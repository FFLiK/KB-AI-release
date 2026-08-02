import json

import httpx
import pytest

from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.base import ExtractionProviderError
from src.providers.extraction.openai import OpenAIEventExtractor
from tests.research_fixtures import candidate, source_document


def completed_response(event_payload: dict) -> dict:
    return {
        "id": "resp_contract",
        "status": "completed",
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": json.dumps({"events": [event_payload]})}],
        }],
        "usage": {"input_tokens": 100, "output_tokens": 50, "input_tokens_details": {"cached_tokens": 10}},
    }


def extractor_for(response_data: dict | bytes, status: int = 200) -> OpenAIEventExtractor:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer configured-test-key"
        payload = json.loads(request.content)
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        assert payload["max_output_tokens"] in {6000, 12000}
        if isinstance(response_data, bytes):
            return httpx.Response(status, content=response_data)
        return httpx.Response(status, json=response_data)

    settings = Settings(openai_api_key="configured-test-key", openai_model="gpt-5.6-terra")
    return OpenAIEventExtractor(settings, httpx.Client(transport=httpx.MockTransport(handler)))


def test_openai_structured_replay_validates_schema_context_source_and_offsets() -> None:
    document = source_document()
    event = candidate(document).model_dump(mode="json")
    result = extractor_for(completed_response(event)).extract(
        document, "RES-TEST", "LOCAL", ReasoningLevel.LOW
    )

    assert len(result.candidates) == 1
    assert result.input_tokens == 100 and result.output_tokens == 50 and result.cached_tokens == 10
    assert result.raw_metadata == {
        "response_id": "resp_contract",
        "response_status": "completed",
        "evidence_offset_corrections": 0,
        "retry_count": 0,
        "max_output_tokens": 6000,
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "AUTHENTICATION_FAILED"), (403, "AUTHENTICATION_FAILED"), (429, "RATE_LIMITED"), (500, "HTTP_500")],
)
def test_openai_http_failures_are_explicit(status, expected) -> None:
    document = source_document()
    with pytest.raises(ExtractionProviderError) as caught:
        extractor_for({"error": {"type": "provider"}}, status).extract(
            document, "RES-TEST", "LOCAL", ReasoningLevel.LOW
        )
    assert caught.value.code == expected and caught.value.http_status == status


@pytest.mark.parametrize(
    ("response_data", "expected"),
    [
        ({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}, "INCOMPLETE_MAX_OUTPUT_TOKENS"),
        ({"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}, "REFUSAL"),
        ({"status": "completed", "output": []}, "EMPTY_OUTPUT"),
        ({"status": "completed", "output_text": "not-json"}, "SCHEMA_VALIDATION_FAILED"),
    ],
)
def test_openai_output_failures_are_explicit(response_data, expected) -> None:
    with pytest.raises(ExtractionProviderError) as caught:
        extractor_for(response_data).extract(source_document(), "RES-TEST", "LOCAL", ReasoningLevel.LOW)
    assert caught.value.code == expected


def test_openai_rejects_context_source_and_evidence_mismatches() -> None:
    document = source_document()
    wrong_run = candidate(document).model_copy(update={"research_run_id": "OTHER"}).model_dump(mode="json")
    with pytest.raises(ExtractionProviderError) as caught:
        extractor_for(completed_response(wrong_run)).extract(document, "RES-TEST", "LOCAL", ReasoningLevel.LOW)
    assert caught.value.code == "CONTEXT_MISMATCH"

    wrong_source = candidate(document).model_dump(mode="json")
    wrong_source["evidence"][0]["source_revision_id"] = "OTHER"
    with pytest.raises(ExtractionProviderError) as caught:
        extractor_for(completed_response(wrong_source)).extract(document, "RES-TEST", "LOCAL", ReasoningLevel.LOW)
    assert caught.value.code == "SOURCE_REVISION_MISMATCH"

    wrong_offset = candidate(document).model_dump(mode="json")
    wrong_offset["evidence"][0]["start_offset"] = 1
    repaired = extractor_for(completed_response(wrong_offset)).extract(
        document, "RES-TEST", "LOCAL", ReasoningLevel.LOW
    )
    assert repaired.raw_metadata["evidence_offset_corrections"] == 1
    assert repaired.candidates[0].evidence[0].start_offset == 0

    missing_quote = candidate(document).model_dump(mode="json")
    missing_quote["evidence"][0]["quote"] = "문서에 없는 인용문"
    with pytest.raises(ExtractionProviderError) as caught:
        extractor_for(completed_response(missing_quote)).extract(
            document, "RES-TEST", "LOCAL", ReasoningLevel.LOW
        )
    assert caught.value.code == "EVIDENCE_INVALID"


def test_openai_timeout_is_explicit() -> None:
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    settings = Settings(openai_api_key="configured-test-key")
    extractor = OpenAIEventExtractor(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ExtractionProviderError) as caught:
        extractor.extract(source_document(), "RES-TEST", "LOCAL", ReasoningLevel.LOW)
    assert caught.value.code == "TIMEOUT"
