from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import Field

from src.contracts.event_candidate import EvidenceRef, ExtractedEventCandidate
from src.contracts.research import ReasoningLevel, StrictModel
from src.contracts.source_document import SourceDocument, SourceType


class SearchRequest(StrictModel):
    query: str
    domain: str
    reasoning_level: ReasoningLevel
    max_results: int = Field(default=10, ge=1, le=20)
    allowed_domains: list[str] = Field(default_factory=list)
    discovery_query: str | None = None
    grounding_metadata: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class SearchHit(StrictModel):
    url: str
    title: str = ""
    snippet: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None
    source_type: SourceType = SourceType.OTHER
    rank: int = Field(ge=1)
    allowed_domains: list[str] = Field(default_factory=list)
    discovery_query: str | None = None
    grounding_metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResultBundle(StrictModel):
    request_id: str
    provider: str
    model: str
    hits: list[SearchHit] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    document_status: str = "NO_DISCRETE_EVENT"
    reason_codes: list[str] = Field(default_factory=list)


class ExtractionResult(StrictModel):
    request_id: str
    provider: str
    model: str
    candidates: list[ExtractedEventCandidate] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    document_status: str = "NO_DISCRETE_EVENT"
    reason_codes: list[str] = Field(default_factory=list)
    # Reference-only retention must be just as auditable as an event. These
    # spans are validated against the stored document before a UI finding is
    # created; a summary without a span is deliberately audit-only.
    reference_summary: str | None = None
    reference_evidence: list[EvidenceRef] = Field(default_factory=list)


class SearchProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


class ExtractionProviderError(RuntimeError):
    def __init__(self, code: str, http_status: int | None = None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


class SearchProvider(ABC):
    @abstractmethod
    def search(self, request: SearchRequest) -> SearchResultBundle: ...


class DocumentFetcher(ABC):
    @abstractmethod
    def fetch(self, hit: SearchHit) -> SourceDocument: ...


class EventExtractor(ABC):
    @abstractmethod
    def extract(
        self,
        document: SourceDocument,
        research_run_id: str,
        domain: str,
        reasoning_level: ReasoningLevel,
        failure_codes: list[str] | None = None,
    ) -> ExtractionResult: ...
