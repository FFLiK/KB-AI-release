import uuid
import time
from datetime import UTC, datetime

from src.contracts.research import (
    AgentType, DocumentResearchOutcome, DocumentResearchStatus, ModelCallRecord,
    ProviderFailureDetail, ResearchRequest, ResearchRunStatus,
)
from src.extraction.model_router import RoutingContext
from src.extraction.identifiers import policy_extractor_id
from src.providers.extraction.policy import PolicyExtractor, PolicyProviderError
from src.providers.base import SearchHit
from src.research_agents.base import BaseResearchAgent
from src.extraction.policy_fallback import deterministic_policy_fallback
from src.storage.repositories import PolicyRepository


class PolicyRegulationResearchAgent(BaseResearchAgent):
    agent_type = AgentType.POLICY_REGULATION
    extraction_domain = "POLICY"
    prompt_version = "policy_regulation_extract.v1"

    def build_queries(self, request: ResearchRequest) -> list[str]:
        area = request.store_location.administrative_area or request.store_location.address
        queries = [
            f"site:bizinfo.go.kr {area} 소상공인 정책자금 공고",
            "site:semas.or.kr 소상공인 대출 상환유예 공고",
            f"{area} 지역신용보증재단 보증 공식 공고",
            f"site:gov.kr {request.business_type_code} 지원사업",
            f"{area} 최저임금 세금 수수료 영업규제 공식",
        ]
        if request.policy_search_terms:
            safe_terms = " ".join(sorted(set(request.policy_search_terms)))
            queries.insert(0, f"site:bizinfo.go.kr {area} {safe_terms} 소상공인 공식 공고")
        if request.projected_cash_burn_date:
            queries.insert(0, f"site:semas.or.kr {area} 긴급 경영안정자금 신청기간")
        return queries

    GANGNAM_POLICY_SEEDS = (
        ("https://www.gangnam.go.kr/contents/SME_LoanSupport/1/view.do?mid=ID02_01080901", "Gangnam SME fund loan support"),
        ("https://www.gangnam.go.kr/contents/Bank_cooperation/1/view.do?mid=ID02_01080904", "Gangnam SME interest and credit-guarantee support"),
    )

    def seeded_hits(self, request: ResearchRequest) -> list[SearchHit]:
        area = " ".join(filter(None, [
            request.store_location.administrative_area, request.store_location.address,
            *request.administrative_area_codes,
        ])).casefold()
        if not any(token in area for token in ("gangnam", "11680")):
            return []
        return [
            SearchHit(url=url, title=title, publisher="Gangnam District Office", rank=index,
                      allowed_domains=["gangnam.go.kr"],
                      discovery_query="??? ???? ???? ???? ?? ???? ??")
            for index, (url, title) in enumerate(self.GANGNAM_POLICY_SEEDS, start=1)
        ]
    def __init__(self, *args, policy_extractor: PolicyExtractor | None = None,
                 policy_repo: PolicyRepository | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy_extractor = policy_extractor
        self.policy_repo = policy_repo

    def run(self, request: ResearchRequest):
        execution = super().run(request)
        if not self.policy_extractor or not self.policy_repo:
            return execution
        selected_ids = set(
            execution.bundle.metadata.get("selected_extraction_source_ids", [])
        )
        usable_ids = selected_ids or {
            outcome.source_id
            for outcome in execution.bundle.document_outcomes
            if outcome.usable_for_extraction
        }
        protected_ids = set(
            execution.bundle.metadata.get("protected_extraction_source_ids", [])
        )
        attempted_source_ids: set[str] = set()
        policy_extraction_started = time.perf_counter()
        for document in execution.documents.values():
            if document.source_id not in usable_ids:
                continue
            if stop_reason := self._stop_reason(request.run_id):
                execution.bundle.status = ResearchRunStatus.PARTIAL
                execution.bundle.diagnostics.timeout_stage = "POLICY_EXTRACTION"
                execution.bundle.diagnostics.skipped_counts["cancellation"] += 1
                execution.bundle.provider_failures.append(ProviderFailureDetail(
                    stage="POLICY_EXTRACTION",
                    provider=type(self.policy_extractor).__name__,
                    document_id=document.source_id,
                    error_type=stop_reason,
                    error_code=stop_reason,
                ))
                break
            deadline = self._active_deadline
            if (
                deadline
                and deadline.exhausted()
                and document.source_id not in protected_ids
            ):
                execution.bundle.status = ResearchRunStatus.PARTIAL
                execution.bundle.diagnostics.timeout_stage = "POLICY_EXTRACTION"
                execution.bundle.diagnostics.skipped_counts[
                    "optional_total_deadline"
                ] += 1
                execution.bundle.provider_failures.append(ProviderFailureDetail(
                    stage="POLICY_EXTRACTION",
                    provider=type(self.policy_extractor).__name__,
                    document_id=document.source_id,
                    error_type="AGENT_WALL_CLOCK_DEADLINE_EXHAUSTED",
                    error_code="AGENT_WALL_CLOCK_DEADLINE_EXHAUSTED",
                ))
                break
            attempted_source_ids.add(document.source_id)
            level = self.router.route_extraction(RoutingContext(
                policy_revision_chain=any(
                    token in document.body_text for token in ("정정", "종료", "CORRECTION", "TERMINATION")
                )
            ))
            try:
                result = self.policy_extractor.extract(document, request.run_id, level.value)
            except PolicyProviderError as exc:
                failure_code = exc.detail.error_code or exc.detail.error_type
                schema_failure = failure_code in {
                    "SCHEMA_VALIDATION_FAILED", "POLICY_SCHEMA_REPAIR_FAILED",
                }
                diagnostic_codes = list(exc.diagnostic_codes)
                if schema_failure and not diagnostic_codes:
                    diagnostic_codes = [
                        "POLICY_SCHEMA_VALIDATION_FAILED",
                        "POLICY_SCHEMA_REPAIR_ATTEMPTED",
                        "POLICY_SCHEMA_REPAIR_FAILED",
                    ]
                if schema_failure:
                    execution.policy_schema_failures.append({
                        "source_id": document.source_id,
                        "source_revision_id": document.revision_id,
                        "raw_provider_response": exc.raw_provider_response,
                        "validation_errors": list(exc.validation_errors),
                    })
                    fallback = deterministic_policy_fallback(document, request.run_id)
                    if fallback is not None:
                        extractor_id = policy_extractor_id(
                            request.run_id, document.source_id, document.revision_id, 1,
                        )
                        fallback = fallback.model_copy(update={
                            "policy_candidate_id": extractor_id,
                            "extractor_policy_candidate_id": extractor_id,
                        })
                        execution.policies.append(fallback)
                        execution.bundle.policy_candidate_ids.append(extractor_id)
                        execution.bundle.metadata.setdefault(
                            "policy_extraction_diagnostics", []
                        ).append({
                            "source_id": document.source_id,
                            "source_revision_id": document.revision_id,
                            "codes": [
                                *diagnostic_codes,
                                "POLICY_DETERMINISTIC_FALLBACK_USED",
                            ],
                            "validation_errors": list(exc.validation_errors),
                        })
                        continue
                    diagnostic_codes = [
                        *diagnostic_codes, "POLICY_EXTRACTION_TERMINAL_FAILURE",
                    ]
                if failure_code == "TIMEOUT":
                    failure_code = "EXTRACTION_REQUEST_TIMEOUT"
                    counts = execution.bundle.diagnostics.operation_timeout_counts
                    counts[failure_code] = counts.get(failure_code, 0) + 1
                detail = exc.detail.model_copy(update={
                    "stage": "POLICY_EXTRACTION",
                    "error_type": failure_code,
                    "error_code": failure_code,
                })
                execution.bundle.provider_failures.append(detail)
                execution.bundle.document_outcomes.append(DocumentResearchOutcome(
                    source_id=document.source_id,
                    source_revision_id=document.revision_id,
                    agent_type=self.agent_type,
                    status=DocumentResearchStatus.PROVIDER_ERROR,
                    reason_codes=diagnostic_codes or [failure_code],
                    final_url_resolved=document.final_url_resolved,
                    usable_for_extraction=True,
                    extraction_attempted=True,
                    body_characters=len(document.body_text),
                ))
                if schema_failure:
                    execution.bundle.metadata.setdefault(
                        "policy_extraction_diagnostics", []
                    ).append({
                        "source_id": document.source_id,
                        "source_revision_id": document.revision_id,
                        "codes": diagnostic_codes,
                        "validation_errors": list(exc.validation_errors),
                    })
                execution.bundle.status = ResearchRunStatus.PARTIAL
                continue
            except Exception:
                detail = ProviderFailureDetail(
                    stage="POLICY_EXTRACTION",
                    provider=type(self.policy_extractor).__name__,
                    document_id=document.source_id,
                    error_type="UNEXPECTED_PROVIDER_FAILURE",
                    error_code="UNEXPECTED_PROVIDER_FAILURE",
                )
                execution.bundle.provider_failures.append(detail)
                execution.bundle.document_outcomes.append(DocumentResearchOutcome(
                    source_id=document.source_id,
                    source_revision_id=document.revision_id,
                    agent_type=self.agent_type,
                    status=DocumentResearchStatus.PROVIDER_ERROR,
                    reason_codes=["UNEXPECTED_PROVIDER_FAILURE"],
                    final_url_resolved=document.final_url_resolved,
                    usable_for_extraction=True,
                    extraction_attempted=True,
                    body_characters=len(document.body_text),
                ))
                execution.bundle.status = ResearchRunStatus.PARTIAL
                continue
            record = ModelCallRecord(
                call_id=f"MC-{uuid.uuid4().hex}",
                provider=result.provider,
                model=result.model,
                reasoning_level=level,
                request_id=result.request_id,
                prompt_version="policy_candidate_extract.v1",
                schema_version="policy_candidate.v1",
                registry_version=request.event_registry_version,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cached_tokens=result.cached_tokens,
                latency_ms=result.latency_ms,
                retry_count=result.retry_count,
                validation_result="SCHEMA_VALIDATED",
                created_at=datetime.now(UTC),
            )
            self.audit_repo.log_model_call(record, request.run_id)
            execution.bundle.model_call_records.append(record)
            if result.diagnostic_codes:
                execution.bundle.metadata.setdefault(
                    "policy_extraction_diagnostics", []
                ).append({
                    "source_id": document.source_id,
                    "source_revision_id": document.revision_id,
                    "codes": list(result.diagnostic_codes),
                    "validation_errors": list(result.validation_errors),
                })
            if result.raw_provider_response is not None:
                execution.policy_schema_failures.append({
                    "source_id": document.source_id,
                    "source_revision_id": document.revision_id,
                    "raw_provider_response": result.raw_provider_response,
                    "validation_errors": list(result.validation_errors),
                })
            for source_local_index, policy in enumerate(result.policies, start=1):
                extractor_id = policy_extractor_id(
                    request.run_id, document.source_id, document.revision_id,
                    source_local_index,
                )
                policy = policy.model_copy(update={
                    "policy_candidate_id": extractor_id,
                    "extractor_policy_candidate_id": extractor_id,
                })
                execution.policies.append(policy)
                execution.bundle.policy_candidate_ids.append(extractor_id)
        elapsed = int((time.perf_counter() - policy_extraction_started) * 1000)
        execution.bundle.diagnostics.elapsed_time_ms_by_stage["extraction"] += elapsed
        execution.bundle.diagnostics.partial_output_counts["policies"] = len(
            execution.policies
        )
        execution.bundle.metadata["stage_elapsed_ms"] = dict(
            execution.bundle.diagnostics.elapsed_time_ms_by_stage
        )
        execution.bundle.metadata["operation_timeout_counts"] = dict(
            execution.bundle.diagnostics.operation_timeout_counts
        )

        for seed_outcome in execution.bundle.metadata.get("seed_outcomes", []):
            source_id = seed_outcome.get("source_id")
            seed_outcome["extraction_attempted"] = (
                bool(source_id) and source_id in attempted_source_ids
            )
            seed_outcome["candidate_produced"] = any(
                source_id in policy.source_ids for policy in execution.policies
            )
            seed_outcome["policy_validation_failed"] = any(
                source_id in policy.source_ids and bool(policy.validation_failure_codes)
                for policy in execution.policies
            )
        if execution.policies:
            event_only_reasons = {
                "NO_EVENT_FOUND",
                "NO_DISCRETE_EVENT",
                "EXTRACTION_NO_CANDIDATES",
            }
            execution.bundle.no_result_reasons = [
                reason for reason in execution.bundle.no_result_reasons
                if reason not in event_only_reasons
            ]
        policy_failures = [
            item for item in execution.bundle.provider_failures
            if item.stage == "POLICY_EXTRACTION"
        ]
        if not execution.policies:
            if execution.bundle.diagnostics.timeout_stage == "POLICY_EXTRACTION":
                reason = "POLICY_EXTRACTION_INCOMPLETE"
            else:
                reason = (
                    "POLICY_EXTRACTION_FAILED" if policy_failures else "NO_POLICY_CANDIDATES"
                )
            if reason not in execution.bundle.no_result_reasons:
                execution.bundle.no_result_reasons.append(reason)
        return execution
