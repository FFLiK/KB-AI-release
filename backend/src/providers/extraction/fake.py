from __future__ import annotations

import uuid

from src.contracts.event_candidate import ExtractedEventCandidate
from src.contracts.research import ReasoningLevel
from src.contracts.source_document import SourceDocument
from src.providers.base import EventExtractor, ExtractionResult


class FakeEventExtractor(EventExtractor):
    def __init__(self, candidates_by_source: dict[str, list[ExtractedEventCandidate]] | None = None,
                 results_by_source: dict[str, ExtractionResult] | None = None):
        self.candidates_by_source=candidates_by_source or {}; self.results_by_source=results_by_source or {}; self.calls=[]
    def extract(self, document: SourceDocument, research_run_id: str, domain: str,
                reasoning_level: ReasoningLevel, failure_codes: list[str] | None = None) -> ExtractionResult:
        self.calls.append((document.source_id, domain, reasoning_level, failure_codes))
        if document.source_id in self.results_by_source:
            return self.results_by_source[document.source_id].model_copy(update={"request_id": f"FAKE-{uuid.uuid4().hex}"}, deep=True)
        candidates=[c.model_copy(deep=True) for c in self.candidates_by_source.get(document.source_id, [])]
        return ExtractionResult(request_id=f"FAKE-{uuid.uuid4().hex}",provider="fake",model="fake-extractor-v1",candidates=candidates,input_tokens=len(document.body_text),output_tokens=len(candidates))
