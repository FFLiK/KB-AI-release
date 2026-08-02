import json

import httpx

from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.extraction.openai import OpenAIEventExtractor
from tests.research_fixtures import candidate, source_document


def test_incomplete_max_output_tokens_retries_once_with_doubled_cap() -> None:
    document = source_document()
    event = candidate(document).model_dump(mode="json")
    requested_caps: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_caps.append(json.loads(request.content)["max_output_tokens"])
        if len(requested_caps) == 1:
            return httpx.Response(
                200,
                json={
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "resp_retry",
                "status": "completed",
                "output_text": json.dumps({"events": [event]}),
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

    settings = Settings(
        openai_api_key="configured-test-key",
        openai_max_output_tokens=6000,
        max_extraction_retries=1,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = OpenAIEventExtractor(settings, client).extract(
            document,
            "RES-TEST",
            "LOCAL",
            ReasoningLevel.LOW,
        )

    assert requested_caps == [6000, 12000]
    assert result.raw_metadata["retry_count"] == 1
    assert result.raw_metadata["max_output_tokens"] == 12000
