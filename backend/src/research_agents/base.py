from __future__ import annotations

import hashlib
import re
import uuid
import time
from dataclasses import dataclass, field, replace
from typing import Callable
from urllib.parse import urljoin
from datetime import UTC, datetime

from src.config.settings import Settings
from src.contracts.attribution import ResearchFinding
from src.contracts.event_candidate import EvidenceRef, ExtractedEventCandidate
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import (
    AccessFailure,
    AgentType,
    DocumentResearchOutcome,
    DocumentResearchStatus,
    ResearchExecutionDiagnostics,
    ModelCallRecord,
    ProviderFailureDetail,
    ReasoningLevel,
    ResearchBundle,
    ResearchRequest,
    ResearchRunStatus,
    SearchQueryRecord,
)
from src.contracts.source_document import AccessStatus, DocumentPageType, SourceDocument
from src.orchestration.run_control import run_control
from src.extraction.model_router import ModelRouter, RoutingContext
from src.extraction.identifiers import event_candidate_id
from src.providers.base import (
    DocumentFetcher,
    EventExtractor,
    ExtractionProviderError,
    SearchHit,
    SearchProvider,
    SearchProviderError,
    SearchRequest,
)
from src.source_snapshot.quality_gate import SourceDisposition, assess_source_quality
from src.source_snapshot.bok import assess_bok_monetary_policy_content, is_bok_document, should_recover_bok_attachment
from src.storage.repositories import AuditRepository, EventRepository, SourceRepository
from src.source_snapshot.url_utils import canonicalize_url
from src.validation.reference_temporal import evaluate_reference_freshness


_SITE_DOMAIN_PATTERN = re.compile(r"(?i)\bsite:([a-z0-9.-]+)")


def _allowed_domains_from_query(query: str) -> list[str]:
    """Translate explicit site: constraints into fetch-time domain controls."""
    return list(dict.fromkeys(
        match.group(1).rstrip(".").lower()
        for match in _SITE_DOMAIN_PATTERN.finditer(query)
    ))


BUDGETS = {
    AgentType.MACRO: (4, 8, 6),
    AgentType.INDUSTRY: (5, 10, 8),
    AgentType.LOCAL_EVENT: (8, 12, 10),
    AgentType.POLICY_REGULATION: (5, 10, 8),
}


def _pre_extraction_rank(
    item: tuple[SourceDocument, str | None, bool],
) -> tuple[int, str, str]:
    document, query, _truncated = item
    trusted = str(document.source_trust_level).split(".")[-1] in {
        "OFFICIAL_TRUSTED", "INSTITUTIONAL_TRUSTED"
    }
    detail = str(document.page_type).split(".")[-1] in {
        "EVENT_DETAIL_PAGE", "LOCAL_NOTICE_DETAIL", "EVENT_ATTACHMENT"
    }
    query_terms = {
        token.casefold() for token in re.findall(
            r"[0-9A-Za-z\uac00-\ud7a3]{2,}", query or ""
        )
    }
    body = f"{document.title}\n{document.body_text[:12000]}".casefold()
    relevance = sum(term in body for term in query_terms)
    substantive = sum(
        marker in body for marker in (
            "effective", "application", "decision", "support",
            "\uacf5\uace0", "\uc2e0\uccad", "\uacb0\uc815", "\uc9c0\uc6d0",
        )
    )
    score = int(trusted) * 100 + int(detail) * 30 + relevance * 5 + substantive * 3
    return (-score, document.canonical_url, document.revision_id)


def _is_stale_listing_row(row_text: str, forecast_start_year: int) -> bool:
    """Avoid spending event-extraction budget on obviously historical list rows."""
    years = [int(value) for value in re.findall(r"\b(20\d{2})\b", row_text)]
    return bool(years) and max(years) < forecast_start_year - 1


def _local_notice_relevance(row_text: str) -> tuple[int, str | None]:
    text = row_text.casefold()
    if any(term in text for term in ("recruit", "appointment", "civil service", "exam", "training", "administrative rule", "\ucc44\uc6a9", "\uc784\uc6a9", "\uc2dc\ud5d8", "\uad50\uc721", "\uace0\uc2dc", "\ud6c8\ub839", "\uaddc\uce59")):
        return -100, "LOCAL_IRRELEVANT_NOTICE"
    score = sum(10 for term in ("construction", "road work", "traffic control", "transit", "pedestrian", "festival", "event", "closure", "redevelopment", "commercial", "safety", "public works", "\uacf5\uc0ac", "\uad50\ud1b5", "\ud1b5\uc81c", "\ubcf4\ud589", "\ucd95\uc81c", "\ud589\uc0ac", "\ud3d0\uc1c4", "\uc7ac\uac1c\ubc1c", "\uc0c1\uad8c", "\uc548\uc804") if term in text)

    # Listing rows are discovery metadata: only deterministic irrelevant categories are skipped here.
    return score, None

def _local_access_reason(document: SourceDocument, *, detail: bool = False) -> str:
    if str(document.access_status).split(".")[-1] == "LOGIN_REQUIRED":
        return "AUTH_REQUIRED_SOURCE"
    if detail and str(document.access_status).split(".")[-1] in {"UNAVAILABLE", "REDIRECT_EXPIRED"}:
        return "DETAIL_FETCH_FAILED"
    return document.retrieval_reason_code or str(document.access_status)


@dataclass(frozen=True)
class AgentDeadline:
    started_at: float
    limit_seconds: float

    @property
    def enabled(self) -> bool:
        return self.limit_seconds > 0

    def elapsed_seconds(self) -> float:
        return max(0.0, time.perf_counter() - self.started_at)

    def exhausted(self) -> bool:
        return self.enabled and self.elapsed_seconds() >= self.limit_seconds

    def remaining_seconds(self) -> float | None:
        if not self.enabled:
            return None
        return max(0.0, self.limit_seconds - self.elapsed_seconds())


@dataclass
class AgentExecution:
    bundle: ResearchBundle
    documents: dict[str, SourceDocument] = field(default_factory=dict)
    candidates: list[ExtractedEventCandidate] = field(default_factory=list)
    policies: list[PolicyCandidate] = field(default_factory=list)
    findings: list[ResearchFinding] = field(default_factory=list)
    policy_schema_failures: list[dict[str, object]] = field(default_factory=list, repr=False)


class BaseResearchAgent:
    agent_type: AgentType
    extraction_domain: str
    prompt_version: str

    def __init__(
        self,
        search: SearchProvider,
        fetcher: DocumentFetcher,
        extractor: EventExtractor,
        source_repo: SourceRepository,
        event_repo: EventRepository,
        audit_repo: AuditRepository,
        router: ModelRouter | None = None,
        settings: Settings | None = None,
        cancellation_checker: Callable[[str], bool] | None = None,
    ):
        self.search_provider = search
        self.fetcher = fetcher
        self.extractor = extractor
        self.source_repo = source_repo
        self.event_repo = event_repo
        self.audit_repo = audit_repo
        self.router = router or ModelRouter()
        self.settings = (
            settings
            or getattr(search, "settings", None)
            or getattr(fetcher, "settings", None)
            or Settings()
        )
        self.cancellation_checker = cancellation_checker
        self._active_deadline: AgentDeadline | None = None

    def _stop_reason(self, run_id: str) -> str | None:
        if self.cancellation_checker and self.cancellation_checker(run_id):
            return "USER_CANCELLED"
        return run_control.stop_reason(run_id)

    def _cancelled(self, run_id: str) -> bool:
        return self._stop_reason(run_id) is not None


    def build_queries(self, request: ResearchRequest) -> list[str]:
        raise NotImplementedError

    def seeded_hits(self, request: ResearchRequest) -> list[SearchHit]:
        """Return bounded first-party sources that remain useful if discovery fails."""
        return []

    @staticmethod
    def _failure_detail(
        stage: str,
        provider: str,
        model: str | None,
        code: str,
        *,
        document_id: str | None = None,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> ProviderFailureDetail:
        return ProviderFailureDetail(
            stage=stage,
            provider=provider,
            model=model,
            document_id=document_id,
            http_status=http_status,
            error_type=code,
            error_code=code,
            retryable=retryable,
        )

    def _reference_finding(
        self,
        request: ResearchRequest,
        document: SourceDocument,
        reason_code: str,
        reference_summary: str | None,
        reference_evidence: list[EvidenceRef],
        query: str | None = None,
    ) -> ResearchFinding | None:
        """Create display-only reference data only from verified extraction spans."""
        trusted = str(document.source_trust_level).split(".")[-1] in {
            "OFFICIAL_TRUSTED", "INSTITUTIONAL_TRUSTED", "VERIFIED_MEDIA",
        }
        quality = assess_source_quality(
            document, query=query, as_of_date=request.as_of_date, agent_type=self.agent_type
        )
        # Listings, navigation shells, and title-only material are never useful
        # reference findings, even if an extractor returned a span for them.
        low_quality_markers = ("menu", "login", "sitemap", "contact", "copyright", "navigation")
        if sum(document.body_text.casefold().count(marker) for marker in low_quality_markers) >= 3:
            return None
        if not trusted or {"QUERY_IRRELEVANT", "STALE_SOURCE", "INSUFFICIENT_CONTENT"}.intersection(quality.reason_codes):
            return None
        if not trusted or quality.disposition in {
            SourceDisposition.REJECT, SourceDisposition.REFERENCE_ONLY,
        }:
            return None
        evidence = [
            item for item in reference_evidence
            if item.source_id == document.source_id
            and item.source_revision_id == document.revision_id
            and 0 <= item.start_offset < item.end_offset <= len(document.body_text)
            and document.body_text[item.start_offset:item.end_offset] == item.quote
            and len(re.sub(r"\s+", " ", item.quote).strip()) >= 40
            and len(re.findall(r"[0-9A-Za-z가-힣]{2,}", item.quote)) >= 5
        ]
        summary_terms = set(re.findall(
            r"[0-9A-Za-z가-힣]{2,}", (reference_summary or "").casefold()
        ))
        evidence_terms = set().union(*(
            set(re.findall(r"[0-9A-Za-z가-힣]{2,}", item.quote.casefold()))
            for item in evidence
        )) if evidence else set()
        if not reference_summary or len(summary_terms) < 3 or len(summary_terms & evidence_terms) < 2:
            return None
        material = f"{request.run_id}|{self.agent_type}|{document.revision_id}|{reason_code}"
        return ResearchFinding(
            finding_id="FND-" + hashlib.sha256(material.encode()).hexdigest()[:20].upper(),
            research_run_id=request.run_id,
            agent_type=self.agent_type,
            domain=self.extraction_domain,
            title=document.title or "Reference material",
            relevance_summary=reference_summary,
            source_ids=[document.source_id],
            source_revision_ids=[document.revision_id],
            evidence=evidence,
            missing_requirements=["STRICT_EVENT_TEMPORAL_AND_IMPACT_EVIDENCE"],
            reason_code=reason_code,
        )
    def _reference_finding_with_diagnostic(
        self,
        request: ResearchRequest,
        document: SourceDocument,
        reason_code: str,
        reference_summary: str | None,
        reference_evidence: list[EvidenceRef],
        query: str | None = None,
    ) -> tuple[ResearchFinding | None, str | list[str] | None]:
        if not reference_summary:
            return None, "REFERENCE_SUMMARY_MISSING"
        if not reference_evidence:
            return None, "REFERENCE_EVIDENCE_MISSING"
        trusted = str(document.source_trust_level).split(".")[-1] in {
            "OFFICIAL_TRUSTED", "INSTITUTIONAL_TRUSTED", "VERIFIED_MEDIA",
        }
        if not trusted:
            return None, "REFERENCE_SOURCE_UNTRUSTED"
        quality = assess_source_quality(
            document, query=query, as_of_date=request.as_of_date,
            agent_type=self.agent_type,
        )
        markers = ("menu", "login", "sitemap", "contact", "copyright", "navigation")
        if sum(document.body_text.casefold().count(item) for item in markers) >= 3:
            return None, "REFERENCE_CONTENT_NOT_SUBSTANTIVE"
        if "QUERY_IRRELEVANT" in quality.reason_codes:
            return None, "REFERENCE_QUERY_IRRELEVANT"
        if {"STALE_SOURCE", "INSUFFICIENT_CONTENT"}.intersection(quality.reason_codes):
            return None, "REFERENCE_CONTENT_NOT_SUBSTANTIVE"
        if quality.disposition in {
            SourceDisposition.REJECT, SourceDisposition.REFERENCE_ONLY,
        }:
            return None, "REFERENCE_CONTENT_NOT_SUBSTANTIVE"

        evidence: list[EvidenceRef] = []
        for original in reference_evidence:
            if (
                original.source_id != document.source_id
                or original.source_revision_id != document.revision_id
            ):
                return None, "REFERENCE_SOURCE_REVISION_MISMATCH"
            item = original.model_copy(deep=True)
            offsets_match = (
                0 <= item.start_offset < item.end_offset <= len(document.body_text)
                and document.body_text[item.start_offset:item.end_offset] == item.quote
            )
            if not offsets_match:
                first = document.body_text.find(item.quote)
                if first < 0:
                    return None, "REFERENCE_QUOTE_NOT_FOUND"
                if document.body_text.find(item.quote, first + 1) >= 0:
                    return None, "REFERENCE_OFFSET_MISMATCH"
                item.start_offset = first
                item.end_offset = first + len(item.quote)
            if (
                len(re.sub(r"\s+", " ", item.quote).strip()) < 40
                or len(re.findall(r"[0-9A-Za-z\uac00-\ud7a3]{2,}", item.quote)) < 5
            ):
                return None, "REFERENCE_CONTENT_NOT_SUBSTANTIVE"
            evidence.append(item)

        summary_terms = set(re.findall(
            r"[0-9A-Za-z\uac00-\ud7a3]{2,}", reference_summary.casefold()
        ))
        evidence_terms = set().union(*(
            set(re.findall(r"[0-9A-Za-z\uac00-\ud7a3]{2,}", item.quote.casefold()))
            for item in evidence
        ))
        if len(summary_terms) < 3 or len(summary_terms & evidence_terms) < 2:
            return None, "REFERENCE_CONTENT_NOT_SUBSTANTIVE"
        freshness = evaluate_reference_freshness(
            request,
            document,
            reference_summary=reference_summary,
            evidence_text=" ".join(item.quote for item in evidence),
        )
        if not freshness.promotable:
            return None, freshness.reason_codes
        material = (
            f"{request.run_id}|{self.agent_type}|{document.revision_id}|{reason_code}"
        )
        return ResearchFinding(
            finding_id="FND-" + hashlib.sha256(material.encode()).hexdigest()[:20].upper(),
            research_run_id=request.run_id,
            agent_type=self.agent_type,
            domain=self.extraction_domain,
            title=document.title or "Reference material",
            relevance_summary=reference_summary,
            source_ids=[document.source_id],
            source_revision_ids=[document.revision_id],
            evidence=evidence,
            missing_requirements=["STRICT_EVENT_TEMPORAL_AND_IMPACT_EVIDENCE"],
            reason_code=reason_code,
            reference_freshness_status=freshness.status,
            reference_temporal_reason_codes=freshness.reason_codes,
        ), None

    @staticmethod
    def _is_retryable_provider_failure(error: SearchProviderError) -> bool:
        if error.http_status in {408, 429}:
            return True
        if error.http_status is not None and error.http_status >= 500:
            return True
        return error.code in {"TIMEOUT", "RATE_LIMITED", "PROVIDER_FAILURE"}

    @staticmethod
    def _search_with_retry(
        provider: SearchProvider,
        request: SearchRequest,
        *,
        max_retries: int,
        sleep=time.sleep,
    ):
        retry_count = 0
        started = time.perf_counter()
        while True:
            try:
                result = provider.search(request)
                result.raw_metadata = {
                    **result.raw_metadata,
                    "retry_count": retry_count,
                    "attempt_count": retry_count + 1,
                    "retry_latency_ms": int((time.perf_counter() - started) * 1000),
                }
                return result
            except SearchProviderError as error:
                if (
                    not BaseResearchAgent._is_retryable_provider_failure(error)
                    or retry_count >= max_retries
                ):
                    error.retry_count = retry_count
                    error.retry_latency_ms = int((time.perf_counter() - started) * 1000)
                    raise
                retry_after = error.retry_after_seconds
                deterministic_jitter = (
                    int(hashlib.sha256(request.request_id.encode()).hexdigest()[:4], 16) % 100
                ) / 1_000
                delay = retry_after if retry_after is not None else min(
                    2.0, 0.2 * (2 ** retry_count) + deterministic_jitter
                )
                retry_count += 1
                sleep(delay)

    def run(self, request: ResearchRequest) -> AgentExecution:
        max_queries, max_docs, max_extract = BUDGETS[self.agent_type]
        run_started = time.perf_counter()
        deadline = AgentDeadline(
            started_at=run_started,
            limit_seconds=self.settings.research_agent_wall_clock_limit_seconds,
        )
        self._active_deadline = deadline
        stage_elapsed_ms = {
            "seed_collection": 0, "search_discovery": 0,
            "document_fetching": 0, "detail_traversal": 0,
            "attachment_processing": 0, "extraction": 0,
            "validation": 0, "result_aggregation": 0,
        }
        operation_timeout_counts: dict[str, int] = {}
        skipped_counts = {
            "document_budget": 0, "extraction_budget": 0, "token_budget": 0,
            "cancellation": 0, "optional_total_deadline": 0,
        }
        timeout_stage: str | None = None
        query_records: list[SearchQueryRecord] = []
        calls: list[ModelCallRecord] = []
        failures: list[AccessFailure] = []
        provider_failures: list[ProviderFailureDetail] = []
        outcomes: list[DocumentResearchOutcome] = []
        hits = []
        seen_discovery_urls: set[str] = set()
        seeded_hits: list[SearchHit] = []
        seen_seed_urls: set[str] = set()
        prefetched_seed_documents: dict[str, SourceDocument] = {}
        seed_lifecycle: dict[str, dict[str, object]] = {}
        recorded_timeout_source_ids: set[str] = set()
        for seed in self.seeded_hits(request):
            canonical_seed_url = canonicalize_url(seed.url)
            if canonical_seed_url in seen_seed_urls:
                continue
            seen_seed_urls.add(canonical_seed_url)
            seeded_hits.append(seed.model_copy(update={"url": canonical_seed_url}))
            seed_lifecycle[canonical_seed_url] = {
                "url": canonical_seed_url,
                "scheduled": True,
                "fetched": False,
                "fetch_failed": False,
            }

        seed_started = time.perf_counter()
        for seed in seeded_hits:
            lifecycle = seed_lifecycle[seed.url]
            if stop_reason := self._stop_reason(request.run_id):
                timeout_stage = "SEED_COLLECTION"
                skipped_counts["cancellation"] += 1
                lifecycle.update(fetch_failed=True, reason_code=stop_reason)
                provider_failures.append(self._failure_detail("SEED_COLLECTION", type(self.fetcher).__name__, None, stop_reason, retryable=False))
                continue
            try:
                prefetched = self.fetcher.fetch(seed)
            except TimeoutError:
                code = "DOCUMENT_FETCH_TIMEOUT"
                operation_timeout_counts[code] = operation_timeout_counts.get(code, 0) + 1
                lifecycle.update(fetch_failed=True, reason_code=code)
                provider_failures.append(self._failure_detail(
                    "SEED_COLLECTION", type(self.fetcher).__name__, None,
                    code, retryable=True,
                ))
                continue
            except Exception:
                code = "DOCUMENT_FETCH_FAILED"
                lifecycle.update(fetch_failed=True, reason_code=code)
                provider_failures.append(self._failure_detail(
                    "SEED_COLLECTION", type(self.fetcher).__name__, None,
                    code, retryable=True,
                ))
                continue
            prefetched_seed_documents[seed.url] = prefetched
            lifecycle["fetched"] = prefetched.access_status == AccessStatus.OK
            lifecycle["fetch_failed"] = prefetched.access_status != AccessStatus.OK
            if prefetched.retrieval_reason_code:
                lifecycle["reason_code"] = prefetched.retrieval_reason_code
            if prefetched.retrieval_reason_code == "DOCUMENT_FETCH_TIMEOUT":
                code = "DOCUMENT_FETCH_TIMEOUT"
                recorded_timeout_source_ids.add(prefetched.source_id)
                operation_timeout_counts[code] = operation_timeout_counts.get(code, 0) + 1
                provider_failures.append(self._failure_detail(
                    "SEED_COLLECTION", type(self.fetcher).__name__, None,
                    code, document_id=prefetched.source_id, retryable=True,
                ))
        stage_elapsed_ms["seed_collection"] = int(
            (time.perf_counter() - seed_started) * 1000
        )


        attempted_queries = self.build_queries(request)[:max_queries]
        failed_queries: list[str] = []
        no_result_queries: list[str] = []
        discovery_started = time.perf_counter()
        for query in attempted_queries:
            if stop_reason := self._stop_reason(request.run_id):
                timeout_stage = "SEARCH_DISCOVERY"
                skipped_counts["cancellation"] += len(attempted_queries) - len(query_records)
                provider_failures.append(self._failure_detail(
                    "SEARCH_DISCOVERY", type(self.search_provider).__name__, None,
                    stop_reason, retryable=False,
                ))
                break
            remaining = deadline.remaining_seconds()
            minimum_documents = min(
                max_docs,
                max(
                    self.settings.research_min_documents_after_discovery,
                    min(len(seeded_hits), self.settings.research_official_seed_reserve),
                ),
            )
            downstream_reserve = (
                minimum_documents * self.settings.http_timeout_seconds
                + self.settings.openai_timeout_seconds
            )
            if remaining is not None and remaining <= downstream_reserve:
                timeout_stage = "SEARCH_DISCOVERY"
                skipped_counts["optional_total_deadline"] += (
                    len(attempted_queries) - len(query_records)
                )
                provider_failures.append(self._failure_detail(
                    "SEARCH_DISCOVERY", type(self.search_provider).__name__, None,
                    "AGENT_WALL_CLOCK_RESERVE_REACHED", retryable=False,
                ))
                break
            level = self.router.route_search(RoutingContext(official_site_constrained="site:" in query))
            req = SearchRequest(
                query=query,
                domain=str(self.agent_type),
                reasoning_level=level,
                max_results=max_docs,
                allowed_domains=_allowed_domains_from_query(query),
                request_id=f"Q-{uuid.uuid4().hex}",
            )
            try:
                max_retries = int(getattr(getattr(self.search_provider, "settings", None), "max_search_retries", 1))
                result = self._search_with_retry(self.search_provider, req, max_retries=max_retries)
            except SearchProviderError as exc:
                failed_queries.append(query)
                failure_code = (
                    "SEARCH_REQUEST_TIMEOUT" if exc.code == "TIMEOUT" else exc.code
                )
                if failure_code == "SEARCH_REQUEST_TIMEOUT":
                    operation_timeout_counts[failure_code] = operation_timeout_counts.get(failure_code, 0) + 1

                provider_name = type(self.search_provider).__name__
                retry_count = int(getattr(exc, "retry_count", 0))
                query_records.append(SearchQueryRecord(
                    query_id=req.request_id,
                    query=query,
                    provider=provider_name,
                    model="UNKNOWN",
                    reasoning_level=level,
                    created_at=datetime.now(UTC),
                    status="FAILED",
                    failure_code=failure_code,
                    retry_count=retry_count,
                    allowed_domains=req.allowed_domains,
                ))
                self.audit_repo.log_search_failure(
                    request.run_id, req, exc, provider_name
                )
                provider_failures.append(self._failure_detail(
                    "SEARCH_DISCOVERY", provider_name, None, failure_code,
                    http_status=exc.http_status,
                    retryable=self._is_retryable_provider_failure(exc),
                ))
                continue
            if not result.hits:
                no_result_queries.append(query)
            query_records.append(SearchQueryRecord(
                query_id=req.request_id,
                query=query,
                provider=result.provider,
                model=result.model,
                reasoning_level=level,
                created_at=datetime.now(UTC),
                status="COMPLETED" if result.hits else "NO_RESULTS",
                retry_count=int(result.raw_metadata.get("retry_count") or 0),
                provider_response_id=(
                    result.raw_metadata.get("response_id") or result.request_id
                ),
                allowed_domains=req.allowed_domains,
                result_order=[
                    canonicalize_url(hit.url)
                    for hit in sorted(result.hits, key=lambda item: (item.rank, item.url))
                ],
            ))
            self.audit_repo.log_search(
                request.run_id, req.request_id, query, result, request=req
            )
            record = ModelCallRecord(
                call_id=f"MC-{uuid.uuid4().hex}",
                provider=result.provider,
                model=result.model,
                reasoning_level=level,
                request_id=result.request_id,
                prompt_version="search_query.v1",
                schema_version="search_result.v1",
                registry_version=request.event_registry_version,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cached_tokens=result.cached_tokens,
                search_query_count=1,
                latency_ms=result.latency_ms,
                retry_count=int(result.raw_metadata.get("retry_count") or 0),
                validation_result="OK" if result.hits else "NO_RESULTS",
                created_at=datetime.now(UTC),
            )
            self.audit_repo.log_model_call(record, request.run_id)
            calls.append(record)
            for hit in result.hits:
                canonical_hit_url = canonicalize_url(hit.url)
                if canonical_hit_url in seen_discovery_urls or canonical_hit_url in seen_seed_urls:
                    continue
                seen_discovery_urls.add(canonical_hit_url)
                hit = hit.model_copy(update={"url": canonical_hit_url})
                if not hit.discovery_query and result.provider != "fake":
                    hit.discovery_query = query
                hits.append(hit)

        stage_elapsed_ms["search_discovery"] = int(
            (time.perf_counter() - discovery_started) * 1000
        )
        # Seeds share the normal document budget and downstream validation gates.
        hits = [*seeded_hits, *hits]
        protected_document_urls = set(seen_seed_urls)
        protected_document_urls.update(
            hit.url for hit in hits[len(seeded_hits):][
                :self.settings.research_min_documents_after_discovery
            ]
        )
        skipped_counts["document_budget"] = max(0, len(hits) - max_docs)


        documents: dict[str, SourceDocument] = {}
        extraction_documents: list[tuple[SourceDocument, str | None, bool]] = []
        all_source_ids: list[str] = []
        seen_snapshot_fingerprints: set[str] = set()
        seen_scheduled_detail_urls: set[str] = set()
        local_metrics = {
            "structured_listings": 0, "detail_links_discovered": 0,
            "detail_pages_fetched": 0, "attachments_fetched": 0,
            "list_row_candidates": 0, "excluded_irrelevant_rows": 0,
            "unique_detail_targets": 0, "skipped_detail_duplicates": 0,
            "extracted_detail_pages": 0,
            "detail_targets_scheduled": 0, "detail_targets_skipped": 0,
            "detail_targets_failed": 0, "detail_target_outcomes": [],
        }
        bok_recovery_diagnostics: list[dict[str, object]] = []
        deterministic_findings: list[ResearchFinding] = []
        seed_source_ids_by_url: dict[str, str] = {}
        fetched_document_ids: set[str] = set()
        document_fetch_attempt_count = 0
        fetch_started = time.perf_counter()
        for hit in hits[:max_docs]:
            if stop_reason := self._stop_reason(request.run_id):
                timeout_stage = "DOCUMENT_FETCH"
                skipped_counts["cancellation"] += 1
                provider_failures.append(self._failure_detail(
                    "DOCUMENT_FETCH", type(self.fetcher).__name__, None,
                    stop_reason, retryable=False,
                ))
                break
            if deadline.exhausted() and hit.url not in protected_document_urls:
                timeout_stage = "DOCUMENT_FETCH"
                skipped_counts["optional_total_deadline"] += 1
                provider_failures.append(self._failure_detail(
                    "DOCUMENT_FETCH", type(self.fetcher).__name__, None,
                    "AGENT_WALL_CLOCK_DEADLINE_EXHAUSTED", retryable=False,
                ))
                break
            document_fetch_attempt_count += 1
            try:
                document = prefetched_seed_documents.get(hit.url)
                if document is None:
                    document = self.fetcher.fetch(hit)
            except TimeoutError:
                code = "DOCUMENT_FETCH_TIMEOUT"
                operation_timeout_counts[code] = operation_timeout_counts.get(code, 0) + 1
                failures.append(AccessFailure(
                    url=hit.url, code=code, detail=code, retryable=True,
                ))
                provider_failures.append(self._failure_detail(
                    "DOCUMENT_FETCH", type(self.fetcher).__name__, None,
                    code, retryable=True,
                ))
                if hit.url in seed_lifecycle:
                    seed_lifecycle[hit.url].update(fetch_failed=True, reason_code=code)
                continue
            except Exception:
                code = "DOCUMENT_FETCH_FAILED"
                failures.append(AccessFailure(
                    url=hit.url, code=code, detail=code, retryable=True,
                ))
                provider_failures.append(self._failure_detail(
                    "DOCUMENT_FETCH", type(self.fetcher).__name__, None,
                    code, retryable=True,
                ))
                if hit.url in seed_lifecycle:
                    seed_lifecycle[hit.url].update(fetch_failed=True, reason_code=code)
                continue
            stored, _ = self.source_repo.save(document, request.run_id)
            if hit.url in seen_seed_urls:
                seed_source_ids_by_url[hit.url] = stored.source_id
            if hit.url in seed_lifecycle:
                seed_lifecycle[hit.url]["source_id"] = stored.source_id
            if stored.access_status == AccessStatus.OK:
                fetched_document_ids.add(stored.source_id)

            all_source_ids.append(stored.source_id)
            if stored.access_status != AccessStatus.OK:
                code = stored.retrieval_reason_code or str(stored.access_status)
                if code in {"DOCUMENT_FETCH_TIMEOUT", "ATTACHMENT_FETCH_TIMEOUT"}:
                    if stored.source_id not in recorded_timeout_source_ids:
                        operation_timeout_counts[code] = operation_timeout_counts.get(code, 0) + 1
                        recorded_timeout_source_ids.add(stored.source_id)
                        provider_failures.append(self._failure_detail(
                            "DOCUMENT_FETCH", type(self.fetcher).__name__, None,
                            code, document_id=stored.source_id, retryable=True,
                        ))
                    if hit.url in seed_lifecycle:
                        seed_lifecycle[hit.url].update(fetch_failed=True, reason_code=code)
                failures.append(AccessFailure(
                    url=stored.canonical_url,
                    code=code,
                    detail=code,
                    retryable=stored.access_status in {
                        AccessStatus.UNAVAILABLE, AccessStatus.REDIRECT_EXPIRED,
                    },
                ))
                outcomes.append(DocumentResearchOutcome(
                    source_id=stored.source_id,
                    source_revision_id=stored.revision_id,
                    agent_type=self.agent_type,
                    status=DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE,
                    reason_codes=[code],
                    final_url_resolved=stored.final_url_resolved,
                ))
                continue
            documents[stored.source_id] = stored
            if stored.snapshot_fingerprint in seen_snapshot_fingerprints:
                outcomes.append(DocumentResearchOutcome(
                    source_id=stored.source_id,
                    source_revision_id=stored.revision_id,
                    agent_type=self.agent_type,
                    status=DocumentResearchStatus.DUPLICATE_SOURCE,
                    reason_codes=["DUPLICATE_SOURCE_SNAPSHOT"],
                    final_url_resolved=stored.final_url_resolved,
                    body_characters=len(stored.body_text),
                ))
                continue
            seen_snapshot_fingerprints.add(stored.snapshot_fingerprint)
            quality = assess_source_quality(
                stored,
                query=hit.discovery_query,
                as_of_date=request.as_of_date,
                agent_type=self.agent_type,
            )
            if (
                self.agent_type == AgentType.LOCAL_EVENT
                and (
                    quality.disposition == SourceDisposition.ROUTE_TO_DETAIL
                    or quality.page_type in {
                        DocumentPageType.STRUCTURED_EVENT_LIST,
                        DocumentPageType.LOCAL_NOTICE_LIST,
                    }
                )
            ):
                local_metrics["structured_listings"] += 1
                local_metrics["detail_links_discovered"] += len(stored.detail_urls)
                local_metrics["list_row_candidates"] += len(stored.structured_event_rows)
                ranked_detail_urls: list[tuple[int, str]] = []
                for row in stored.structured_event_rows:
                    score, relevance_reason = _local_notice_relevance(row.text)
                    row_reason = "STALE_LISTING_ROW" if _is_stale_listing_row(row.text, request.forecast_start.year) else relevance_reason
                    if row_reason:
                        outcomes.append(DocumentResearchOutcome(
                            source_id=stored.source_id,
                            source_revision_id=stored.revision_id,
                            agent_type=self.agent_type,
                            status=DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE,
                            reason_codes=[row_reason],
                            extraction_attempted=False,
                            final_url_resolved=stored.final_url_resolved,
                            body_characters=len(row.text),
                            page_type=str(quality.page_type),
                            classification_reasons=quality.classification_reasons,
                        ))
                        continue
                    ranked_detail_urls.extend((score, canonicalize_url(urljoin(stored.canonical_url, url))) for url in row.detail_urls)
                local_metrics["excluded_irrelevant_rows"] += sum(1 for item in outcomes if item.source_id == stored.source_id and item.reason_codes and item.reason_codes[0].startswith("LOCAL_"))
                ranked_urls = list(dict.fromkeys(url for _, url in sorted(ranked_detail_urls, key=lambda item: (-item[0], item[1]))))
                if not ranked_urls:
                    ranked_urls = list(dict.fromkeys(canonicalize_url(urljoin(stored.canonical_url, url)) for url in stored.detail_urls))
                local_metrics["unique_detail_targets"] += len(ranked_urls)
                fresh_ranked_urls = [url for url in ranked_urls if url not in seen_scheduled_detail_urls]
                # Compare only the same deduplicated URL set that is scheduled.
                duplicate_count = len(ranked_urls) - len(fresh_ranked_urls)
                local_metrics["skipped_detail_duplicates"] += duplicate_count
                local_metrics["detail_targets_skipped"] += duplicate_count
                seen_scheduled_detail_urls.update(fresh_ranked_urls)
                ranked_urls = fresh_ranked_urls
                over_detail_budget = max(0, len(ranked_urls) - 6)
                local_metrics["detail_targets_skipped"] += over_detail_budget
                ranked_urls = ranked_urls[:6]
                if over_detail_budget:
                    local_metrics["detail_target_outcomes"].append({"outcome": "DETAIL_BUDGET_EXHAUSTED", "count": over_detail_budget})
                local_metrics["detail_targets_scheduled"] += len(ranked_urls)
                traversal = getattr(self.fetcher, "fetch_with_detail_pages", None)
                traversal_parent = stored.model_copy(update={"detail_urls": ranked_urls})
                related = traversal(hit, parent=traversal_parent) if callable(traversal) else []
                child_targets = {canonicalize_url(child.canonical_url): child for child in related if child.parent_source_id == stored.source_id}
                for target_url in ranked_urls:
                    child = child_targets.get(target_url)
                    if child is None:
                        reason = "DETAIL_TRAVERSAL_UNAVAILABLE" if not callable(traversal) else "DETAIL_FETCH_FAILED"
                        local_metrics["detail_targets_failed"] += 1
                    elif child.access_status == AccessStatus.OK:
                        reason = "DETAIL_FETCHED"
                    elif child.access_status == AccessStatus.DOMAIN_NOT_ALLOWED:
                        reason = "DETAIL_DOMAIN_NOT_ALLOWED"
                        local_metrics["detail_targets_skipped"] += 1
                    else:
                        reason = "DETAIL_FETCH_FAILED"
                        local_metrics["detail_targets_failed"] += 1
                    local_metrics["detail_target_outcomes"].append({"url": target_url, "outcome": reason})
                for child in related:
                    attached, _ = self.source_repo.save(child, request.run_id)
                    all_source_ids.append(attached.source_id)
                    if attached.access_status != AccessStatus.OK:
                        outcomes.append(DocumentResearchOutcome(
                            source_id=attached.source_id,
                            source_revision_id=attached.revision_id,
                            agent_type=self.agent_type,
                            status=DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE,
                            reason_codes=[_local_access_reason(attached, detail=True)],
                            final_url_resolved=attached.final_url_resolved,
                            page_type=str(attached.page_type),
                        ))
                        continue
                    documents[attached.source_id] = attached
                    if attached.snapshot_fingerprint in seen_snapshot_fingerprints:
                        outcomes.append(DocumentResearchOutcome(
                            source_id=attached.source_id,
                            source_revision_id=attached.revision_id,
                            agent_type=self.agent_type,
                            status=DocumentResearchStatus.DUPLICATE_SOURCE,
                            reason_codes=["DUPLICATE_SOURCE_SNAPSHOT"],
                            final_url_resolved=attached.final_url_resolved,
                            body_characters=len(attached.body_text),
                        ))
                        continue
                    seen_snapshot_fingerprints.add(attached.snapshot_fingerprint)
                    child_quality = assess_source_quality(
                        attached,
                        query=hit.discovery_query,
                        as_of_date=request.as_of_date,
                        agent_type=self.agent_type,
                    )
                    if attached.parent_source_id and attached.content_type and "pdf" in attached.content_type.casefold():
                        local_metrics["attachments_fetched"] += 1
                    else:
                        local_metrics["detail_pages_fetched"] += 1
                    if not (child_quality.usable or child_quality.disposition == SourceDisposition.LOW_PRIORITY_EXTRACT):
                        outcomes.append(DocumentResearchOutcome(
                            source_id=attached.source_id,
                            source_revision_id=attached.revision_id,
                            agent_type=self.agent_type,
                            status=DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE,
                            reason_codes=child_quality.reason_codes,
                            final_url_resolved=attached.final_url_resolved,
                            body_characters=child_quality.body_characters,
                            page_type=str(child_quality.page_type),
                            classification_reasons=child_quality.classification_reasons,
                        ))
                        continue
                    extraction_documents.append((
                        attached.model_copy(update={"body_text": child_quality.extraction_body}),
                        hit.discovery_query,
                        child_quality.truncated,
                    ))
                    local_metrics["extracted_detail_pages"] += 1
                outcomes.append(DocumentResearchOutcome(
                    source_id=stored.source_id,
                    source_revision_id=stored.revision_id,
                    agent_type=self.agent_type,
                    status=DocumentResearchStatus.STRUCTURED_LIST_TRAVERSED,
                    reason_codes=["LOCAL_DETAIL_TRAVERSAL_COMPLETED"],
                    final_url_resolved=stored.final_url_resolved,
                    body_characters=quality.body_characters,
                    page_type=str(quality.page_type),
                    classification_reasons=quality.classification_reasons,
                ))
                continue
            route_and_traverse = quality.disposition in {
                SourceDisposition.ROUTE_TO_DETAIL,
                SourceDisposition.TRAVERSE_LIST,
                SourceDisposition.FETCH_ATTACHMENTS,
                SourceDisposition.EXTRACT_AND_TRAVERSE,
            }
            if (
                self.agent_type != AgentType.LOCAL_EVENT
                and route_and_traverse
                and not (self.agent_type == AgentType.MACRO and is_bok_document(stored))
            ):
                bounded_parent = stored.model_copy(update={
                    "detail_urls": stored.detail_urls[:6],
                    "attachment_urls": stored.attachment_urls[:3],
                })
                if stored.detail_urls:
                    traversal = getattr(self.fetcher, "fetch_with_detail_pages", None)
                    related = traversal(hit, parent=bounded_parent) if callable(traversal) else []
                elif stored.attachment_urls:
                    traversal = getattr(self.fetcher, "fetch_with_attachments", None)
                    related = (
                        traversal(hit, parent=bounded_parent)[1:] if callable(traversal) else []
                    )
                else:
                    traversal = None
                    related = []
                if not callable(traversal):
                    outcomes.append(DocumentResearchOutcome(
                        source_id=stored.source_id,
                        source_revision_id=stored.revision_id,
                        agent_type=self.agent_type,
                        status=DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE,
                        reason_codes=[
                            f"UNSUPPORTED_ROUTE_{self.agent_type.value}_{quality.disposition.value}"
                        ],
                        final_url_resolved=stored.final_url_resolved,
                        usable_for_extraction=quality.usable,
                        body_characters=quality.body_characters,
                        page_type=str(quality.page_type),
                        classification_reasons=quality.classification_reasons,
                    ))
                    if not quality.usable:
                        continue
                else:
                    traversed_count = 0
                    for child in related:
                        attached, _ = self.source_repo.save(child, request.run_id)
                        all_source_ids.append(attached.source_id)
                        if attached.access_status != AccessStatus.OK:
                            outcomes.append(DocumentResearchOutcome(
                                source_id=attached.source_id,
                                source_revision_id=attached.revision_id,
                                agent_type=self.agent_type,
                                status=DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE,
                                reason_codes=[_local_access_reason(attached, detail=True)],
                                final_url_resolved=attached.final_url_resolved,
                            ))
                            continue
                        documents[attached.source_id] = attached
                        if attached.snapshot_fingerprint in seen_snapshot_fingerprints:
                            continue
                        seen_snapshot_fingerprints.add(attached.snapshot_fingerprint)
                        child_quality = assess_source_quality(
                            attached, query=hit.discovery_query,
                            as_of_date=request.as_of_date, agent_type=self.agent_type,
                        )
                        if child_quality.usable or child_quality.disposition == SourceDisposition.LOW_PRIORITY_EXTRACT:
                            extraction_documents.append((
                                attached.model_copy(update={
                                    "body_text": child_quality.extraction_body,
                                    "page_type": child_quality.page_type,
                                    "classification_reasons": child_quality.classification_reasons,
                                }),
                                hit.discovery_query,
                                child_quality.truncated,
                            ))
                            traversed_count += 1
                    outcomes.append(DocumentResearchOutcome(
                        source_id=stored.source_id,
                        source_revision_id=stored.revision_id,
                        agent_type=self.agent_type,
                        status=DocumentResearchStatus.STRUCTURED_LIST_TRAVERSED,
                        reason_codes=[
                            f"{self.agent_type.value}_DETAIL_TRAVERSAL_COMPLETED"
                        ],
                        final_url_resolved=stored.final_url_resolved,
                        usable_for_extraction=quality.usable,
                        body_characters=quality.body_characters,
                    ))
                    if not quality.usable:
                        continue
            bok_recovery_code: str | None = None
            bok_detail_discovered = bool(stored.detail_urls)
            bok_detail_fetched = False
            bok_attachment_discovered = bool(stored.attachment_urls)
            bok_attachment_fetched = False
            bok_text_extracted = bool(stored.body_text.strip())
            if self.agent_type == AgentType.MACRO and is_bok_document(stored):
                assessment = assess_bok_monetary_policy_content(stored)
                if not assessment.usable and stored.detail_urls:
                    bok_recovery_code = "BOK_DETAIL_DOCUMENT_NOT_FOUND"
                    for detail_url in stored.detail_urls[:3]:
                        detail = self.fetcher.fetch(SearchHit(
                            url=detail_url,
                            rank=hit.rank,
                            title=stored.title,
                            publisher=stored.publisher,
                            allowed_domains=hit.allowed_domains or ["bok.or.kr"],
                            discovery_query=hit.discovery_query,
                        ))
                        recovered, _ = self.source_repo.save(detail, request.run_id)
                        all_source_ids.append(recovered.source_id)
                        if recovered.access_status != AccessStatus.OK:
                            continue
                        bok_detail_fetched = True
                        bok_text_extracted = bok_text_extracted or bool(recovered.body_text.strip())
                        bok_attachment_discovered = (
                            bok_attachment_discovered or bool(recovered.attachment_urls)
                        )
                        documents[recovered.source_id] = recovered
                        recovered_quality = assess_source_quality(
                            recovered, query=hit.discovery_query,
                            as_of_date=request.as_of_date, agent_type=self.agent_type,
                        )
                        if assess_bok_monetary_policy_content(recovered).usable:
                            stored = recovered
                            quality = recovered_quality
                            bok_recovery_code = "BOK_DETAIL_DOCUMENT_RECOVERED"
                            break
                elif not assessment.usable:
                    bok_recovery_code = "BOK_LISTING_PAGE_ONLY"
            if (
                self.agent_type == AgentType.MACRO
                and should_recover_bok_attachment(stored)
                and callable(getattr(self.fetcher, "fetch_with_attachments", None))
            ):
                bok_attachment_discovered = bok_attachment_discovered or bool(stored.attachment_urls)
                bounded_bok_parent = stored.model_copy(update={
                    "attachment_urls": stored.attachment_urls[:3],
                })
                related = self.fetcher.fetch_with_attachments(hit, parent=bounded_bok_parent)[1:]
                for attachment in related:
                    attached, _ = self.source_repo.save(attachment, request.run_id)
                    all_source_ids.append(attached.source_id)
                    if attached.access_status != AccessStatus.OK:
                        bok_recovery_code = "BOK_ATTACHMENT_FETCH_FAILED"
                        continue
                    bok_attachment_fetched = True
                    bok_text_extracted = bok_text_extracted or bool(attached.body_text.strip())
                    documents[attached.source_id] = attached
                    attachment_quality = assess_source_quality(
                        attached,
                        query=hit.discovery_query,
                        as_of_date=request.as_of_date,
                        agent_type=self.agent_type,
                    )
                    if (
                        (attachment_quality.usable or attachment_quality.disposition == SourceDisposition.LOW_PRIORITY_EXTRACT)
                        and assess_bok_monetary_policy_content(attached).usable
                    ):
                        stored = attached
                        quality = attachment_quality
                        bok_recovery_code = "BOK_ATTACHMENT_DOCUMENT_RECOVERED"
                        break
            if self.agent_type == AgentType.MACRO and is_bok_document(document):
                bok_recovery_diagnostics.append({
                    "source_id": document.source_id,
                    "reason_codes": [bok_recovery_code] if bok_recovery_code else [],
                    "detail_discovered": bok_detail_discovered,
                    "detail_fetched": bok_detail_fetched,
                    "attachment_discovered": bok_attachment_discovered,
                    "attachment_fetched": bok_attachment_fetched,
                    "text_extracted": bok_text_extracted,
                    "decision_facts_validated": assess_bok_monetary_policy_content(stored).usable,
                    "terminal_reason": None if assess_bok_monetary_policy_content(stored).usable else bok_recovery_code,
                })
            if self.agent_type == AgentType.MACRO and is_bok_document(stored):
                bok_assessment = assess_bok_monetary_policy_content(stored)
                if not bok_assessment.usable:
                    quality = replace(
                        quality,
                        usable=False,
                        reason_codes=list(dict.fromkeys(
                            [*quality.reason_codes, *bok_assessment.reason_codes, *([bok_recovery_code] if bok_recovery_code else [])]
                        )),
                    )
                elif bok_assessment.facts and bok_assessment.facts.decision_type == "HOLD":
                    facts = bok_assessment.facts
                    raw = stored.body_text
                    start = facts.evidence_start_offset
                    end = facts.evidence_end_offset
                    quote = facts.evidence_text
                    identity = (
                        f"{facts.decision_date}|{facts.decision_type}|"
                        f"{facts.current_rate_percent}"
                    )
                    evidence = EvidenceRef(
                        evidence_id="EVI-" + hashlib.sha256(
                            f"{identity}|{stored.revision_id}".encode()
                        ).hexdigest()[:20].upper(),
                        source_id=stored.source_id,
                        source_revision_id=stored.revision_id,
                        field_paths=[
                            "decision_date", "decision_type", "current_rate_percent"
                        ],
                        quote=quote,
                        start_offset=start,
                        end_offset=end,
                    )
                    deterministic_findings.append(ResearchFinding(
                        finding_id="FND-BOK-" + hashlib.sha256(
                            identity.encode()
                        ).hexdigest()[:16].upper(),
                        research_run_id=request.run_id,
                        agent_type=self.agent_type,
                        domain=self.extraction_domain,
                        title="Bank of Korea base-rate decision",
                        relevance_summary=(
                            "Bank of Korea held the base rate at "
                            f"{facts.current_rate_percent}% on {facts.decision_date}."
                        ),
                        temporal_raw=facts.decision_date,
                        source_ids=[stored.source_id],
                        source_revision_ids=[stored.revision_id],
                        evidence=[evidence],
                        missing_requirements=["NO_RATE_CHANGE"],
                        reason_code="BOK_RATE_HOLD_REFERENCE_ONLY",
                        recommended_follow_up="MONITOR_NEXT_BOK_DECISION",
                        rate_selection_method=facts.rate_selection_method,
                        rate_evidence_id=evidence.evidence_id,
                        reference_freshness_status="CURRENT_OFFICIAL_STATE",
                        reference_temporal_reason_codes=[],
                    ))
                    outcomes.append(DocumentResearchOutcome(
                        source_id=stored.source_id,
                        source_revision_id=stored.revision_id,
                        agent_type=self.agent_type,
                        status=DocumentResearchStatus.REFERENCE_FINDINGS_ONLY,
                        reason_codes=["BOK_RATE_HOLD_REFERENCE_ONLY"],
                        final_url_resolved=stored.final_url_resolved,
                        usable_for_extraction=True,
                        extraction_attempted=False,
                        finding_count=1,
                        body_characters=len(stored.body_text),
                    ))
                    continue
            if not (quality.usable or quality.disposition == SourceDisposition.LOW_PRIORITY_EXTRACT):
                outcomes.append(DocumentResearchOutcome(
                    source_id=stored.source_id,
                    source_revision_id=stored.revision_id,
                    agent_type=self.agent_type,
                    status=DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE,
                    reason_codes=["DYNAMIC_ENDPOINT_REQUIRED"] if quality.disposition == SourceDisposition.RESOLVE_DYNAMIC_SOURCE else quality.reason_codes,
                    final_url_resolved=stored.final_url_resolved,
                    body_characters=quality.body_characters,
                    page_type=str(quality.page_type),
                    classification_reasons=quality.classification_reasons,
                ))
                continue
            extraction_document = stored.model_copy(update={"body_text": quality.extraction_body, "page_type": quality.page_type, "classification_reasons": quality.classification_reasons})
            extraction_documents.append((extraction_document, hit.discovery_query, quality.truncated))

        stage_elapsed_ms["document_fetching"] = int(
            (time.perf_counter() - fetch_started) * 1000
        )

        prefilter_input_count = len(extraction_documents)
        seed_source_ids = set(seed_source_ids_by_url.values())
        ranked_extraction_documents = sorted(
            extraction_documents,
            key=lambda item: (
                0 if item[0].source_id in seed_source_ids else 1,
                *_pre_extraction_rank(item),
            ),
        )
        extraction_documents = ranked_extraction_documents[:max_extract]
        skipped_counts["extraction_budget"] = max(
            0, prefilter_input_count - len(extraction_documents)
        )
        protected_extraction_ids = seed_source_ids | {
            item[0].source_id for item in extraction_documents[
                :self.settings.research_min_documents_after_discovery
            ]
        }

        for document, _query, _truncated in ranked_extraction_documents[max_extract:]:
            outcomes.append(DocumentResearchOutcome(
                source_id=document.source_id,
                source_revision_id=document.revision_id,
                agent_type=self.agent_type,
                status=DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE,
                reason_codes=["PREFILTER_BUDGET_EXCLUDED"],
                final_url_resolved=document.final_url_resolved,
                usable_for_extraction=False,
                extraction_attempted=False,
                body_characters=len(document.body_text),
                page_type=str(document.page_type),
                classification_reasons=document.classification_reasons,
            ))
        candidates: list[ExtractedEventCandidate] = []
        findings: list[ResearchFinding] = list(deterministic_findings)
        extraction_started = time.perf_counter()
        for document, _query, truncated in extraction_documents:
            if stop_reason := self._stop_reason(request.run_id):
                timeout_stage = "EVENT_EXTRACTION"
                skipped_counts["cancellation"] += 1
                provider_failures.append(self._failure_detail(
                    "EVENT_EXTRACTION", type(self.extractor).__name__, None,
                    stop_reason, retryable=False,
                ))
                break
            if deadline.exhausted() and document.source_id not in protected_extraction_ids:
                timeout_stage = "EVENT_EXTRACTION"
                skipped_counts["optional_total_deadline"] += 1
                provider_failures.append(self._failure_detail(
                    "EVENT_EXTRACTION", type(self.extractor).__name__, None,
                    "AGENT_WALL_CLOCK_DEADLINE_EXHAUSTED", retryable=False,
                ))
                break
            context = RoutingContext(
                has_relative_dates=any(token in document.body_text.casefold() for token in ("today", "tomorrow", "next week", "current")),
                document_event_count_hint=max(1, document.body_text.casefold().count("event")),
            )
            level = self.router.route_extraction(context)
            try:
                result = self.extractor.extract(
                    document, request.run_id, self.extraction_domain, level
                )
            except ExtractionProviderError as exc:
                failure_code = (
                    "EXTRACTION_REQUEST_TIMEOUT" if exc.code == "TIMEOUT" else exc.code
                )
                if failure_code == "EXTRACTION_REQUEST_TIMEOUT":
                    operation_timeout_counts[failure_code] = operation_timeout_counts.get(failure_code, 0) + 1

                provider_failures.append(self._failure_detail(
                    "EVENT_EXTRACTION", type(self.extractor).__name__, None, failure_code,
                    document_id=document.source_id,
                    http_status=exc.http_status,
                    retryable=failure_code in {"EXTRACTION_REQUEST_TIMEOUT", "RATE_LIMITED", "PROVIDER_FAILURE"},
                ))
                outcomes.append(DocumentResearchOutcome(
                    source_id=document.source_id,
                    source_revision_id=document.revision_id,
                    agent_type=self.agent_type,
                    status=DocumentResearchStatus.PROVIDER_ERROR,
                    reason_codes=[failure_code],
                    final_url_resolved=document.final_url_resolved,
                    usable_for_extraction=True,
                    extraction_attempted=True,
                    body_characters=len(document.body_text),
                    truncated=truncated,
                ))
                continue
            self.audit_repo.log_extraction(
                request.run_id, result.request_id, document.revision_id, result
            )
            record = ModelCallRecord(
                call_id=f"MC-{uuid.uuid4().hex}",
                provider=result.provider,
                model=result.model,
                reasoning_level=level,
                request_id=result.request_id,
                prompt_version=self.prompt_version,
                schema_version="event_candidate.v1",
                registry_version=request.event_registry_version,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cached_tokens=result.cached_tokens,
                latency_ms=result.latency_ms,
                retry_count=int(result.raw_metadata.get("retry_count") or 0),
                validation_result="SCHEMA_VALIDATED",
                created_at=datetime.now(UTC),
            )
            self.audit_repo.log_model_call(record, request.run_id)
            calls.append(record)
            for source_local_index, candidate in enumerate(result.candidates, start=1):
                candidate = candidate.model_copy(update={
                    "candidate_id": event_candidate_id(
                        request.run_id, self.extraction_domain, document.source_id,
                        document.revision_id, source_local_index,
                    ),
                }, deep=True)
                original = documents.get(document.source_id)
                if original and document.body_text != original.body_text:
                    row_start = original.body_text.find(document.body_text)
                    if row_start >= 0:
                        for evidence in candidate.evidence:
                            if evidence.source_id != document.source_id:
                                continue
                            start_offset = row_start + evidence.start_offset
                            end_offset = row_start + evidence.end_offset
                            if original.body_text[start_offset:end_offset] == evidence.quote:
                                evidence.start_offset = start_offset
                                evidence.end_offset = end_offset
                self.event_repo.save_candidate(candidate)
                candidates.append(candidate)
            status = (
                DocumentResearchStatus.CANDIDATES_EXTRACTED
                if result.candidates
                else DocumentResearchStatus(result.document_status)
            )
            finding_count = 0
            if status in {
                DocumentResearchStatus.REFERENCE_FINDINGS_ONLY,
                DocumentResearchStatus.INSUFFICIENT_TEMPORAL_EVIDENCE,
                DocumentResearchStatus.INSUFFICIENT_IMPACT_EVIDENCE,
            } and not result.candidates:
                fallback_codes = {
                    DocumentResearchStatus.INSUFFICIENT_TEMPORAL_EVIDENCE: "REFERENCE_ONLY_MISSING_EFFECTIVE_DATE",
                    DocumentResearchStatus.INSUFFICIENT_IMPACT_EVIDENCE: "REFERENCE_ONLY_MISSING_IMPACT_EVIDENCE",
                }
                reason = fallback_codes.get(
                    status, result.reason_codes[0] if result.reason_codes else "STRICT_EVENT_REQUIREMENTS_MISSING"
                )
                original = documents.get(document.source_id, document)
                reference_evidence = [item.model_copy(deep=True) for item in result.reference_evidence]
                if document.body_text != original.body_text:
                    row_start = original.body_text.find(document.body_text)
                    if row_start >= 0:
                        for evidence in reference_evidence:
                            evidence.start_offset += row_start
                            evidence.end_offset += row_start
                finding, reference_rejection = self._reference_finding_with_diagnostic(
                    request, original, reason, result.reference_summary, reference_evidence, _query
                )
                if finding:
                    findings.append(finding)
                    finding_count = 1
                elif reference_rejection:
                    rejection_codes = (
                        [reference_rejection]
                        if isinstance(reference_rejection, str)
                        else reference_rejection
                    )
                    result.reason_codes = list(dict.fromkeys([
                        *result.reason_codes, *rejection_codes,
                    ]))
            outcomes.append(DocumentResearchOutcome(
                source_id=document.source_id,
                source_revision_id=document.revision_id,
                agent_type=self.agent_type,
                status=status,
                reason_codes=result.reason_codes,
                final_url_resolved=document.final_url_resolved,
                usable_for_extraction=True,
                extraction_attempted=True,
                candidate_count=len(result.candidates),
                finding_count=finding_count,
                input_tokens=result.input_tokens,
                latency_ms=result.latency_ms,
                body_characters=len(document.body_text),
                truncated=truncated,
            ))

        stage_elapsed_ms["extraction"] = int(
            (time.perf_counter() - extraction_started) * 1000
        )
        seed_outcomes = []
        for seed_url in sorted(seen_seed_urls):
            source_id = seed_source_ids_by_url.get(seed_url)
            source_outcomes = [
                outcome for outcome in outcomes if outcome.source_id == source_id
            ]
            seed_outcomes.append({
                **seed_lifecycle.get(seed_url, {}),
                "url": seed_url,
                "source_id": source_id,
                "fetched": bool(seed_lifecycle.get(seed_url, {}).get("fetched")),
                "fetch_failed": bool(seed_lifecycle.get(seed_url, {}).get("fetch_failed")),
                "extraction_attempted": any(
                    outcome.extraction_attempted for outcome in source_outcomes
                ),
                "candidate_produced": any(
                    outcome.candidate_count > 0 for outcome in source_outcomes
                ),
                "rejected_by_quality": any(
                    outcome.status == DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE
                    for outcome in source_outcomes
                ),
                "policy_validation_failed": False,
                "reason_codes": sorted({
                    code for outcome in source_outcomes for code in outcome.reason_codes
                }),
            })

        for outcome in outcomes:
            timeout_codes = {
                code for code in outcome.reason_codes
                if code in {"DOCUMENT_FETCH_TIMEOUT", "ATTACHMENT_FETCH_TIMEOUT"}
            }
            for code in timeout_codes:
                if outcome.source_id in recorded_timeout_source_ids:
                    continue
                recorded_timeout_source_ids.add(outcome.source_id)
                operation_timeout_counts[code] = operation_timeout_counts.get(code, 0) + 1
                provider_failures.append(self._failure_detail(
                    "ATTACHMENT_FETCH" if code == "ATTACHMENT_FETCH_TIMEOUT" else "DOCUMENT_FETCH",
                    type(self.fetcher).__name__, None, code,
                    document_id=outcome.source_id, retryable=True,
                ))

        partial = bool(failures or provider_failures) or not extraction_documents
        for outcome in outcomes:
            if not outcome.source_revision_id:
                continue
            try:
                audit_document = self.source_repo.get(
                    outcome.source_id, outcome.source_revision_id
                )
            except (LookupError, ValueError):
                continue
            outcome.snapshot_fingerprint = audit_document.snapshot_fingerprint
            outcome.routing_metadata_version = audit_document.routing_metadata_version

        no_result_reasons: list[str] = []
        if not candidates:
            if not hits:
                no_result_reasons.extend([
                    "NO_EVENT_FOUND", "NO_RELEVANT_SEARCH_RESULTS",
                ])
            elif (
                timeout_stage in {"SEED_COLLECTION", "DOCUMENT_FETCH"}
                or self._cancelled(request.run_id)
            ) and not fetched_document_ids:
                no_result_reasons.append("DOCUMENT_COLLECTION_INCOMPLETE")
            elif not fetched_document_ids:
                no_result_reasons.append("SEARCH_RESULTS_FETCH_FAILED")
            elif not extraction_documents:
                no_result_reasons.extend([
                    "NO_USABLE_SOURCES", "DOCUMENTS_REJECTED_BY_QUALITY",
                ])
            elif provider_failures:
                no_result_reasons.append("EXTRACTION_DEGRADED")
            elif findings:
                no_result_reasons.append("REFERENCE_FINDINGS_ONLY")
            else:
                no_result_reasons.extend([
                    "NO_DISCRETE_EVENT", "EXTRACTION_NO_CANDIDATES",
                ])
        configured_limits: dict[str, int | float | None] = {
            "search_query_limit": max_queries,
            "discovered_document_limit": max_queries * max_docs,
            "selected_document_limit": max_docs,
            "detail_page_limit": 6,
            "attachment_limit": 3,
            "extraction_call_limit": max_extract,
            "input_character_limit": max_extract * 30000,
            "search_retry_limit": self.settings.max_search_retries,
            "extraction_retry_limit": self.settings.max_extraction_retries,
            "agent_wall_clock_limit_seconds": (
                self.settings.research_agent_wall_clock_limit_seconds or None
            ),
            "search_request_timeout_seconds": self.settings.gemini_timeout_seconds,
            "document_fetch_timeout_seconds": self.settings.http_timeout_seconds,
            "attachment_fetch_timeout_seconds": self.settings.http_timeout_seconds,
            "extraction_request_timeout_seconds": self.settings.openai_timeout_seconds,
            "analysis_job_timeout_seconds": self.settings.analysis_job_timeout_seconds,
            "minimum_documents_after_discovery": self.settings.research_min_documents_after_discovery,
            "official_seed_reserve": self.settings.research_official_seed_reserve,
        }
        stage_elapsed_ms["result_aggregation"] = max(
            0, int((time.perf_counter() - run_started) * 1000)
            - sum(stage_elapsed_ms.values())
        )
        diagnostics = ResearchExecutionDiagnostics(
            discovered_hit_count=len(hits) - len(seeded_hits),
            fetched_document_count=len(fetched_document_ids),
            usable_document_count=len(extraction_documents),
            timeout_stage=timeout_stage,
            operation_timeout_counts=operation_timeout_counts,
            partial_output_counts={
                "documents": len(documents), "candidates": len(candidates),
                "findings": len(findings),
            },
            configured_limits=configured_limits,
            elapsed_time_ms_by_stage=stage_elapsed_ms,
            skipped_counts=skipped_counts,
            cancellation_requested=self._cancelled(request.run_id),
        )
        bundle = ResearchBundle(
            research_run_id=request.run_id,
            agent_type=self.agent_type,
            status=ResearchRunStatus.PARTIAL if partial else ResearchRunStatus.COMPLETED,
            search_queries=query_records,
            source_document_ids=sorted(set(all_source_ids)),
            event_candidate_ids=[item.candidate_id for item in candidates],
            access_failures=failures,
            no_result_reasons=no_result_reasons,
            model_call_records=calls,
            document_outcomes=outcomes,
            provider_failures=provider_failures,
            diagnostics=diagnostics,
            metadata={
                "discovery_hit_count": len(hits) - len(seeded_hits),
                "seeded_source_count": len(seeded_hits),
                "attempted_queries": attempted_queries,
                "failed_queries": failed_queries,
                "no_result_queries": no_result_queries,
                "seed_outcomes": seed_outcomes,
                "resolved_source_count": len(documents),
                "fetched_document_count": len(fetched_document_ids),
                "document_fetch_attempt_count": document_fetch_attempt_count,
                "selected_extraction_source_ids": sorted(
                    document.source_id for document, _query, _truncated in extraction_documents
                ),
                "protected_extraction_source_ids": sorted(protected_extraction_ids),
                "deduplicated_document_count": sum(
                    1 for item in outcomes if item.status == DocumentResearchStatus.DUPLICATE_SOURCE
                ),
                "usable_document_count": len(extraction_documents),
                "usable_candidate_count": len(candidates),
                "extraction_input_tokens": sum(
                    record.input_tokens for record in calls
                    if record.prompt_version != "search_query.v1"
                ),
                "extraction_tokens_per_usable_candidate": (
                    sum(
                        record.input_tokens for record in calls
                        if record.prompt_version != "search_query.v1"
                    ) / len(candidates)
                    if candidates else None
                ),
                "local_collection": local_metrics if self.agent_type == AgentType.LOCAL_EVENT else {},
                "bok_recovery_diagnostics": bok_recovery_diagnostics,
                "prefilter": {
                    "input_document_count": prefilter_input_count,
                    "selected_document_count": len(extraction_documents),
                    "reduction_ratio": (
                        (prefilter_input_count - len(extraction_documents))
                        / prefilter_input_count
                        if prefilter_input_count else 0.0
                    ),
                    "document_limit": max_docs,
                    "model_call_limit": max_extract,
                    "detail_page_limit": 6,
                    "attachment_limit": 3,
                    "input_character_limit": max_extract * 30000,
                    "retry_limit": int(getattr(
                        getattr(self.search_provider, "settings", None),
                        "max_search_retries", 1,
                    )),
                    "wall_clock_limit_seconds": self.settings.research_agent_wall_clock_limit_seconds or None,
                },
                "timeout_stage": timeout_stage,
                "operation_timeout_counts": operation_timeout_counts,
                "stage_elapsed_ms": stage_elapsed_ms,
                "skipped_counts": skipped_counts,
                "configured_limits": configured_limits,
                "routing": {
                    "hard_rejected_documents": sum(1 for item in outcomes if item.status == DocumentResearchStatus.SOURCE_CONTENT_UNUSABLE),
                    "traversed_lists": local_metrics["structured_listings"],
                    "discovered_detail_links": local_metrics["detail_links_discovered"],
                    "fetched_detail_pages": local_metrics["detail_pages_fetched"],
                    "fetched_attachments": local_metrics["attachments_fetched"],
                    "dynamic_source_recovery_attempts": 0,
                    "low_priority_extraction_attempts": 0,
                    "candidates_per_1000_extraction_tokens": (
                        len(candidates) * 1000 / sum(record.input_tokens for record in calls if record.prompt_version != "search_query.v1")
                        if any(record.input_tokens for record in calls if record.prompt_version != "search_query.v1") else None
                    ),
                },
            },
        )
        return AgentExecution(
            bundle=bundle,
            documents=documents,
            candidates=candidates,
            findings=findings,
        )
