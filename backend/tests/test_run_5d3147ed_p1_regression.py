"""Deterministic P1 regressions for temporal, lifecycle, eligibility and retry semantics."""
from __future__ import annotations

from datetime import date

from src.contracts.attribution import ResearchResultSummary
from src.contracts.event_candidate import EvidenceRef, EventImpact, ExtractedEventCandidate, ExtractionMetadata, LocationRaw, TemporalRaw
from src.contracts.research import ReasoningLevel
from src.normalization.geo_normalizer import GeoResolution
from src.orchestration.analysis_orchestrator import _research_summary
from src.orchestration.research_pipeline import ResearchPipelineResult
from src.providers.base import SearchProvider, SearchProviderError, SearchRequest, SearchResultBundle
from src.relief.eligibility_rules import evaluate_policy_eligibility_detailed
from src.relief.policy_schema import PolicySchema
from src.validation.research_validator import ResearchEventValidator
from tests.e2e.support import load_store
from tests.research_fixtures import candidate, research_request, source_document


class CountingGeocoder:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, *_args, **_kwargs) -> GeoResolution:
        self.calls += 1
        raise AssertionError("Expired events must be rejected before geocoding")


def test_historical_event_stops_before_geocoding_and_has_unambiguous_lifecycle() -> None:
    document = source_document()
    item = candidate(document, start="2025-08-01", end="2025-08-03", lat=None, lon=None)
    geocoder = CountingGeocoder()

    outcome = ResearchEventValidator(geocoder=geocoder).validate(
        item, {document.source_id: document}, research_request()
    )

    assert outcome.status == "REJECTED"
    assert "FORECAST_WINDOW_NOT_OVERLAPPED" in outcome.failure_codes
    assert geocoder.calls == 0
    assert outcome.lifecycle_stages[-1] == "OUTSIDE_FORECAST_WINDOW"
    assert "VALIDATED" not in outcome.lifecycle_stages

    summary = _research_summary(
        ResearchPipelineResult(run_id="RUN", rejected_events=[outcome]),
        ResearchPipelineResult(run_id="RUN"), [], load_store(),
    )
    rejected = summary.rejected_events[0]
    assert rejected.event_type_signal_enabled is True
    assert rejected.candidate_signal_eligible is False
    assert rejected.signal_enabled is False


def test_size_language_does_not_become_an_industry_restriction() -> None:
    policy = PolicySchema(
        policy_id="POL-SIZE", name="SME capital support", provider="Agency",
        budget_status="AVAILABLE",
        industry_inclusions=[
            "SME", "SMALL_BUSINESS", "\uc911\uc18c\uae30\uc5c5", "\uc18c\uc0c1\uacf5\uc778",
        ],
    )
    status, _, logs = evaluate_policy_eligibility_detailed(load_store(), policy, "11", date(2026, 7, 30))
    assert status == "ELIGIBLE_ON_DECLARED_RULES"
    assert any(log["dimension"] == "BUSINESS_SIZE" for log in logs)


class Flaky503Search(SearchProvider):
    def __init__(self) -> None:
        self.calls = 0

    def search(self, request: SearchRequest) -> SearchResultBundle:
        self.calls += 1
        if self.calls == 1:
            raise SearchProviderError("HTTP_503", 503)
        return SearchResultBundle(request_id=request.request_id, provider="fake", model="fake", raw_metadata={})


def test_http_503_is_retryable_with_a_bounded_retry() -> None:
    from src.research_agents.macro.agent import MacroResearchAgent

    search = Flaky503Search()
    # The agent helper is kept separate from a live provider; this verifies the
    # retry classification and bounded retry without a network call.
    assert MacroResearchAgent._is_retryable_provider_failure(
        SearchProviderError("HTTP_503", 503)
    )
    result = MacroResearchAgent._search_with_retry(
        search,
        SearchRequest(
            query="official decision", domain="MACRO", reasoning_level=ReasoningLevel.LOW,
            max_results=1, request_id="RETRY-503",
        ),
        max_retries=1,
        sleep=lambda _delay: None,
    )
    assert result.raw_metadata["retry_count"] == 1
    assert search.calls == 2
