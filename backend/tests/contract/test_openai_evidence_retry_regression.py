import json

import httpx

from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.extraction.openai import OpenAIEventExtractor
from tests.research_fixtures import candidate, source_document


def test_invalid_evidence_retries_once_with_failure_code() -> None:
    document = source_document()
    valid_event = candidate(document).model_dump(mode="json")
    invalid_event = json.loads(json.dumps(valid_event))
    invalid_event["evidence"][0]["quote"] = "quote absent from stored body"
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        if calls == 2:
            assert "EVIDENCE_INVALID" in payload["input"]
        event = invalid_event if calls == 1 else valid_event
        return httpx.Response(
            200,
            json={
                "id": f"resp_evidence_{calls}",
                "status": "completed",
                "output_text": json.dumps({"events": [event]}),
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

    settings = Settings(
        openai_api_key="configured-test-key",
        max_extraction_retries=1,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = OpenAIEventExtractor(settings, client).extract(
            document,
            "RES-TEST",
            "LOCAL",
            ReasoningLevel.LOW,
        )

    assert calls == 2
    assert len(result.candidates) == 1
    assert result.raw_metadata["validation_retry_count"] == 1
