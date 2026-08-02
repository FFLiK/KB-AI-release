from __future__ import annotations

import json
import time
import uuid

import httpx

from src.config.settings import Settings
from src.contracts.event_candidate import ExtractedEventCandidate
from src.contracts.research import ReasoningLevel
from src.contracts.source_document import SourceDocument
from src.providers.base import EventExtractor, ExtractionResult
from src.providers.extraction.prompts import build_prompt
from src.providers.extraction.schema_utils import strict_array_response_schema


class LocalEventExtractor(EventExtractor):
    """Adapter for an OpenAI-compatible local or NVIDIA NIM inference server."""
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or Settings()
        self.client = client

    def extract(
        self,
        document: SourceDocument,
        research_run_id: str,
        domain: str,
        reasoning_level: ReasoningLevel,
        failure_codes: list[str] | None = None,
    ) -> ExtractionResult:
        if not self.settings.local_llm_base_url:
            raise RuntimeError("LOCAL_LLM_BASE_URL is required")
        prompt_content = build_prompt(
            domain,
            document.body_text,
            document.source_id,
            document.revision_id,
            failure_codes,
            research_run_id=research_run_id,
            model=self.settings.local_llm_model,
        )
        payload = {
            "model": self.settings.local_llm_model,
            "messages": [{"role": "user", "content": prompt_content}],
            "temperature": 0,
        }
        started = time.perf_counter()
        client = self.client or httpx.Client(timeout=self.settings.openai_timeout_seconds)
        headers = {"Content-Type": "application/json"}
        api_key = self.settings.nvidia_api_key or self.settings.openai_api_key
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            url = self.settings.local_llm_base_url.rstrip("/")
            if not url.endswith("/chat/completions"):
                url += "/chat/completions"
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        finally:
            if self.client is None:
                client.close()

        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        events_list = parsed.get("events") if isinstance(parsed, dict) and "events" in parsed else parsed
        if not isinstance(events_list, list):
            events_list = [events_list]
        candidates = [ExtractedEventCandidate.model_validate(x) for x in events_list]
        usage = data.get("usage", {})
        return ExtractionResult(
            request_id=f"EXT-{uuid.uuid4().hex}",
            provider="local",
            model=self.settings.local_llm_model,
            candidates=candidates,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
