from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor,as_completed
import re
import unicodedata
import time
from dataclasses import dataclass,field

from src.contracts.attribution import ResearchFinding
from src.extraction.identifiers import event_candidate_id
from src.contracts.canonical_event import CanonicalEvent
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import ResearchBundle, ResearchRequest, ResearchRunStatus
from src.contracts.source_document import SourceDocument
from src.providers.base import ExtractionProviderError
from src.research_agents.base import AgentExecution,BaseResearchAgent
from src.storage.repositories import AuditRepository,EventRepository,PolicyRepository
from src.validation.evidence_validator import validate_event_evidence
from src.validation.reconciler import EventReconciler,assign_cause_groups
from src.validation.research_validator import ResearchEventValidator,ValidationOutcome
from src.validation.policy_validator import PolicyReconciler, validate_policy_candidate
from src.operations.metrics import metrics
from src.validation.policy_identity import canonicalize_policy_identity


@dataclass
class ResearchPipelineResult:
    run_id:str; bundles:list[ResearchBundle]=field(default_factory=list); documents:dict[str,SourceDocument]=field(default_factory=dict)
    accepted_events:list[CanonicalEvent]=field(default_factory=list); rejected_events:list[ValidationOutcome]=field(default_factory=list); policies:list[PolicyCandidate]=field(default_factory=list); errors:list[str]=field(default_factory=list); findings:list[ResearchFinding]=field(default_factory=list)


class ResearchPipeline:
    def __init__(self,agents:list[BaseResearchAgent],validator:ResearchEventValidator,event_repo:EventRepository,policy_repo:PolicyRepository,audit_repo:AuditRepository):
        self.agents=agents; self.validator=validator; self.event_repo=event_repo; self.policy_repo=policy_repo; self.audit_repo=audit_repo; self.reconciler=EventReconciler()
    def run(self,request:ResearchRequest)->ResearchPipelineResult:
        if not self.audit_repo.get_run(request.run_id): self.audit_repo.create_run(request)
        self.audit_repo.update_run(request.run_id,"RUNNING"); executions=[]; errors=[]
        with ThreadPoolExecutor(max_workers=min(4,len(self.agents) or 1)) as pool:
            futures={pool.submit(agent.run,request):agent for agent in self.agents}
            for future in as_completed(futures):
                try: executions.append(future.result())
                except Exception as exc: errors.append(f"{futures[future].agent_type}:{type(exc).__name__}")
        documents={sid:doc for execution in executions for sid,doc in execution.documents.items()}; outcomes=[]
        for execution in executions:
            validation_started = time.perf_counter()
            for candidate in execution.candidates:
                outcome=self.validator.validate(candidate,documents,request)
                retry_accepted=None
                if outcome.retryable:
                    source=documents.get(candidate.evidence[0].source_id) if candidate.evidence else None
                    if source:
                        agent=next((a for a in self.agents if a.extraction_domain==str(candidate.domain)),None)
                        if agent:
                            try:
                                retry=agent.extractor.extract(source,request.run_id,str(candidate.domain),agent.router.route_extraction(__import__('src.extraction.model_router',fromlist=['RoutingContext']).RoutingContext(failure_codes=tuple(outcome.failure_codes))),outcome.failure_codes)
                            except ExtractionProviderError as exc:
                                outcome.retry_attempted=True
                                outcome.retry_outcome=f"PROVIDER_ERROR_{exc.code}"
                                errors.append(f"VALIDATION_RETRY:{exc.code}")
                                retry=None
                            retry_outcomes=[]
                            for source_local_index, retried in enumerate(retry.candidates if retry else [], start=1):
                                retried = retried.model_copy(update={
                                    "candidate_id": event_candidate_id(
                                        request.run_id, agent.extraction_domain, source.source_id,
                                        source.revision_id, source_local_index, retry_attempt=1,
                                    ),
                                }, deep=True)
                                self.event_repo.save_candidate(retried)
                                retry_outcomes.append(self.validator.validate(retried,documents,request))
                            retry_accepted=next((x for x in retry_outcomes if x.status=="ACCEPTED"),None)
                            retry_result=retry_accepted or (retry_outcomes[0] if retry_outcomes else None)
                            outcome.retry_attempted=True
                            if retry is not None:
                                outcome.retry_outcome=retry_result.status if retry_result else "NO_CANDIDATE"
                            outcome.retry_candidate_id=retry_result.candidate.candidate_id if retry_result else None
                outcomes.append(outcome)
                if retry_accepted:
                    outcomes.append(retry_accepted)
                    previous="EXTRACTED"
                    for stage in ("SCHEMA_VALIDATED","EVIDENCE_VALIDATED","NORMALIZED","TEMPORAL_GEO_VALIDATED","RELEVANCE_VALIDATED"):
                        self.audit_repo.log_validation(request.run_id,retry_accepted.candidate.candidate_id,previous,stage)
                        previous=stage
                if outcome.status=="ACCEPTED":
                    previous="EXTRACTED"
                    for stage in ("SCHEMA_VALIDATED","EVIDENCE_VALIDATED","NORMALIZED","TEMPORAL_GEO_VALIDATED","RELEVANCE_VALIDATED"):
                        self.audit_repo.log_validation(request.run_id,outcome.candidate.candidate_id,previous,stage)
                        previous=stage
                else:
                    self.audit_repo.log_validation(request.run_id,outcome.candidate.candidate_id,"EXTRACTED",outcome.status,outcome.failure_codes[0] if outcome.failure_codes else None,",".join(outcome.failure_codes))
            validation_elapsed = int((time.perf_counter() - validation_started) * 1000)
            stage_timings = execution.bundle.diagnostics.elapsed_time_ms_by_stage
            stage_timings["validation"] = (
                stage_timings.get("validation", 0) + validation_elapsed
            )
            execution.bundle.metadata["stage_elapsed_ms"] = dict(
                execution.bundle.diagnostics.elapsed_time_ms_by_stage
            )

        accepted_raw=[o.event for o in outcomes if o.event is not None and o.status=="ACCEPTED"]
        accepted,duplicates_or_conflicts=self.reconciler.reconcile(accepted_raw, as_of_date=request.as_of_date)
        accepted=assign_cause_groups(accepted,request.official_indicator_snapshot_ids)
        for event in accepted+duplicates_or_conflicts: self.event_repo.save_canonical(event)
        for event in accepted:
            for candidate_id in event.candidate_ids:
                self.audit_repo.log_validation(request.run_id,candidate_id,"RELEVANCE_VALIDATED","DEDUPLICATED")
                self.audit_repo.log_validation(request.run_id,candidate_id,"DEDUPLICATED","ACCEPTED")
        for event in duplicates_or_conflicts:
            for candidate_id in event.candidate_ids:
                self.audit_repo.log_validation(request.run_id,candidate_id,"DEDUPLICATED",event.validation_status,event.validation_failure_codes[0] if event.validation_failure_codes else None)
        policies=[]
        for execution in executions:
            policy_validation_started = time.perf_counter()
            validated_for_execution = []
            for policy in execution.policies:
                identified = canonicalize_policy_identity(policy, documents)
                validated = validate_policy_candidate(identified, documents, request.as_of_date)
                validated_for_execution.append(validated)
                policies.append(validated)
            validation_elapsed = int(
                (time.perf_counter() - policy_validation_started) * 1000
            )
            stage_timings = execution.bundle.diagnostics.elapsed_time_ms_by_stage
            stage_timings["validation"] = (
                stage_timings.get("validation", 0) + validation_elapsed
            )
            execution.bundle.metadata["stage_elapsed_ms"] = dict(
                execution.bundle.diagnostics.elapsed_time_ms_by_stage
            )
            for seed_outcome in execution.bundle.metadata.get("seed_outcomes", []):
                source_id = seed_outcome.get("source_id")
                seed_outcome["policy_validation_failed"] = any(
                    source_id in policy.source_ids
                    and bool(policy.validation_failure_codes)
                    for policy in validated_for_execution
                )
        policies=PolicyReconciler().reconcile(policies, documents)
        for policy in policies: self.policy_repo.save(policy)
        rejected=[o for o in outcomes if o.status!="ACCEPTED"]
        metrics.increment("event_accepted_total", len(accepted))
        metrics.increment("event_rejected_total", len(rejected) + len(duplicates_or_conflicts))
        metrics.increment("duplicate_conflict_total", len(duplicates_or_conflicts))
        metrics.increment("research_provider_failure_total", len(errors))
        for execution in executions:
            metrics.increment("research_fetch_failure_total", len(execution.bundle.access_failures))
            for record in execution.bundle.model_call_records:
                kind = "search" if record.prompt_version == "search_query.v1" else "extraction"
                metrics.increment(f"research_{kind}_input_tokens_total", record.input_tokens)
                metrics.increment(f"research_{kind}_output_tokens_total", record.output_tokens)
                metrics.observe(f"research_{kind}_latency_ms", record.latency_ms)
                if record.estimated_cost is not None:
                    metrics.observe("research_estimated_cost_usd", record.estimated_cost)
                else:
                    metrics.increment("research_cost_rate_unconfigured_total")
                metrics.increment("research_model_retry_total", record.retry_count)
            metrics.increment(
                "research_provider_failure_total", len(execution.bundle.provider_failures)
            )
            metrics.increment(
                "research_usable_document_total",
                int(execution.bundle.metadata.get("usable_document_count") or 0),
            )
            metrics.increment(
                "research_duplicate_document_total",
                int(execution.bundle.metadata.get("deduplicated_document_count") or 0),
            )
            metrics.increment(
                "research_reference_finding_total",
                sum(item.finding_count for item in execution.bundle.document_outcomes),
            )
        evidence_codes = {"QUOTE_NOT_FOUND", "OFFSET_MISMATCH", "PROMPT_INJECTION_DETECTED"}
        for outcome in rejected:
            for code in outcome.failure_codes:
                metrics.increment(f"validation_failure_{code.lower()}_total")
            if evidence_codes.intersection(outcome.failure_codes):
                metrics.increment("evidence_rejection_total")
        partial = bool(errors) or any(
            execution.bundle.status == ResearchRunStatus.PARTIAL for execution in executions
        )
        status = "PARTIAL" if partial else "COMPLETED"
        self.audit_repo.update_run(request.run_id, status)
# Both risk and policy pipelines can produce verified reference material.
        # Deduplicate only exact source revision/reason/title equivalents so that
        # revisions remain separately auditable in the UI.
        findings_by_key = {}
        for finding in [finding for execution in executions for finding in execution.findings]:
            normalized_title = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", finding.title)).strip().casefold()
            key = (tuple(sorted(finding.source_revision_ids)), finding.reason_code, normalized_title)
            findings_by_key.setdefault(key, finding)
        findings = [findings_by_key[key] for key in sorted(findings_by_key)]
        return ResearchPipelineResult(
            request.run_id, [e.bundle for e in executions], documents,
            accepted, rejected, policies, errors, findings,
        )
