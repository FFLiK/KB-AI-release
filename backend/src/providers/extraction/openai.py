from __future__ import annotations

import json
import time
import uuid

import httpx
from pydantic import ValidationError

from src.config.settings import Settings
from src.contracts.event_candidate import EvidenceRef, ExtractedEventCandidate
from src.contracts.research import ReasoningLevel
from src.contracts.source_document import SourceDocument
from src.providers.base import EventExtractor, ExtractionProviderError, ExtractionResult
from src.providers.extraction.prompts import build_prompt
from src.providers.extraction.schema_utils import strict_array_response_schema
from src.validation.evidence_validator import validate_event_evidence


class OpenAIEventExtractor(EventExtractor):
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or Settings()
        self.client = client

    @staticmethod
    def _provider_error(response: httpx.Response) -> ExtractionProviderError:
        if response.status_code in {401, 403}:
            return ExtractionProviderError("AUTHENTICATION_FAILED", response.status_code)
        if response.status_code == 429:
            return ExtractionProviderError("RATE_LIMITED", response.status_code)
        return ExtractionProviderError(f"HTTP_{response.status_code}", response.status_code)

    @staticmethod
    def _output_text(data: dict) -> str:
        parts: list[str] = []
        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "refusal":
                    raise ExtractionProviderError("REFUSAL")
                if content.get("type") == "output_text":
                    parts.append(str(content.get("text") or ""))
        return str(data.get("output_text") or "") or "".join(parts)

    def extract(
        self,
        document: SourceDocument,
        research_run_id: str,
        domain: str,
        reasoning_level: ReasoningLevel,
        failure_codes: list[str] | None = None,
        _validation_retry_count: int = 0,
    ) -> ExtractionResult:
        if not self.settings.openai_api_key:
            raise ExtractionProviderError("NOT_CONFIGURED")
        schema = strict_array_response_schema(ExtractedEventCandidate.model_json_schema(), "events")
        schema["properties"]["document_status"] = {
            "type": "string",
            "enum": [
                "CANDIDATES_EXTRACTED", "REFERENCE_FINDINGS_ONLY", "NO_DISCRETE_EVENT",
                "INSUFFICIENT_TEMPORAL_EVIDENCE", "INSUFFICIENT_IMPACT_EVIDENCE",
                "OUTSIDE_FORECAST_CONTEXT", "SOURCE_CONTENT_UNUSABLE",
            ],
        }
        schema["properties"]["reason_codes"] = {
            "type": "array", "items": {"type": "string"},
        }
        schema["properties"]["reference_summary"] = {"type": ["string", "null"]}
        schema["properties"]["reference_evidence"] = {
            "type": "array", "items": EvidenceRef.model_json_schema(),
        }
        schema["required"] = [
            "events", "document_status", "reason_codes", "reference_summary",
            "reference_evidence",
        ]
        request_id = f"EXT-{uuid.uuid4().hex}"
        payload = {
            "model": self.settings.openai_model,
            "input": build_prompt(
                domain,
                document.body_text,
                document.source_id,
                document.revision_id,
                failure_codes,
                research_run_id=research_run_id,
                model=self.settings.openai_model,
            ),
            "reasoning": {"effort": reasoning_level.value.lower()},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "event_candidates",
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": self.settings.openai_max_output_tokens,
        }
        started = time.perf_counter()
        client = self.client or httpx.Client(timeout=self.settings.openai_timeout_seconds)
        retry_count = 0
        try:
            while True:
                try:
                    response = client.post(
                        "https://api.openai.com/v1/responses",
                        headers={
                            "Authorization": f"Bearer {self.settings.openai_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                except httpx.TimeoutException as exc:
                    raise ExtractionProviderError("TIMEOUT") from exc
                except httpx.HTTPError as exc:
                    raise ExtractionProviderError("PROVIDER_FAILURE") from exc
                if response.status_code >= 400:
                    raise self._provider_error(response)
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ExtractionProviderError("MALFORMED_RESPONSE", response.status_code) from exc
                incomplete_reason = str(
                    (data.get("incomplete_details") or {}).get("reason") or ""
                ) if isinstance(data, dict) and data.get("status") == "incomplete" else ""
                if (
                    incomplete_reason == "max_output_tokens"
                    and retry_count < self.settings.max_extraction_retries
                ):
                    retry_count += 1
                    payload["max_output_tokens"] *= 2
                    continue
                break
        finally:
            if self.client is None:
                client.close()
        if not isinstance(data, dict):
            raise ExtractionProviderError("MALFORMED_RESPONSE", response.status_code)
        if data.get("status") == "incomplete":
            reason = str((data.get("incomplete_details") or {}).get("reason") or "UNKNOWN")
            raise ExtractionProviderError(f"INCOMPLETE_{reason.upper()}", response.status_code)
        if data.get("status") not in {None, "completed"}:
            raise ExtractionProviderError(f"RESPONSE_STATUS_{str(data.get('status')).upper()}", response.status_code)
        output_text = self._output_text(data)
        if not output_text:
            raise ExtractionProviderError("EMPTY_OUTPUT", response.status_code)
        try:
            parsed = json.loads(output_text)
            raw_events = parsed["events"]
            if not isinstance(raw_events, list):
                raise TypeError("events must be a list")
            candidates = [ExtractedEventCandidate.model_validate(item) for item in raw_events]
            document_status = str(parsed.get("document_status") or "NO_DISCRETE_EVENT")
            reason_codes = [str(item) for item in (parsed.get("reason_codes") or [])]
            reference_summary = parsed.get("reference_summary")
            reference_evidence = [EvidenceRef.model_validate(item) for item in (parsed.get("reference_evidence") or [])]
            if candidates:
                document_status = "CANDIDATES_EXTRACTED"
        except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
            raise ExtractionProviderError("SCHEMA_VALIDATION_FAILED", response.status_code) from exc
        snapshots = {document.source_id: document.body_text}
        offset_corrections = 0
        for candidate in candidates:
            for evidence in candidate.evidence:
                if document.body_text[evidence.start_offset:evidence.end_offset] == evidence.quote:
                    continue
                starts: list[int] = []
                cursor = 0
                while True:
                    found = document.body_text.find(evidence.quote, cursor)
                    if found < 0:
                        break
                    starts.append(found)
                    cursor = found + 1
                if len(starts) == 1:
                    evidence.start_offset = starts[0]
                    evidence.end_offset = starts[0] + len(evidence.quote)
                    offset_corrections += 1
        for candidate in candidates:
            if candidate.research_run_id != research_run_id or str(candidate.domain) != domain:
                raise ExtractionProviderError("CONTEXT_MISMATCH", response.status_code)
            if any(
                evidence.source_id != document.source_id
                or evidence.source_revision_id != document.revision_id
                for evidence in candidate.evidence
            ):
                raise ExtractionProviderError("SOURCE_REVISION_MISMATCH", response.status_code)
            valid, _ = validate_event_evidence(
                [evidence.model_dump() for evidence in candidate.evidence], snapshots
            )
            if not valid:
                if _validation_retry_count < self.settings.max_extraction_retries:
                    retried = self.extract(
                        document,
                        research_run_id,
                        domain,
                        reasoning_level,
                        failure_codes=[*(failure_codes or []), "EVIDENCE_INVALID"],
                        _validation_retry_count=_validation_retry_count + 1,
                    )
                    retried.raw_metadata["validation_retry_count"] = (
                        _validation_retry_count + 1
                    )
                    return retried
                raise ExtractionProviderError("EVIDENCE_INVALID", response.status_code)
        usage = data.get("usage") or {}
        return ExtractionResult(
            request_id=request_id,
            provider="openai",
            model=self.settings.openai_model,
            candidates=candidates,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cached_tokens=int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0),
            latency_ms=int((time.perf_counter() - started) * 1000),
            document_status=document_status,
            reason_codes=reason_codes,
            reference_summary=reference_summary,
            reference_evidence=reference_evidence,
            raw_metadata={
                "response_id": data.get("id"),
                "response_status": data.get("status"),
                "evidence_offset_corrections": offset_corrections,
                "retry_count": retry_count,
                "max_output_tokens": payload["max_output_tokens"],
            },
        )
