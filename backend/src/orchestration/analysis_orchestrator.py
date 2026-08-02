"""Single, versioned backend analysis orchestration path."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from src.contracts.analysis import (
    AnalysisResultV1,
    EvidenceReplayContext,
    AnalysisRunStatus,
    AnalysisSection,
    PolicyResultBundle,
    PolicySearchContext,
    SectionExecution,
    SectionStatus,
    TraceabilityManifest,
    VersionManifest,
    analysis_payload_hash,
    canonical_json_hash,
)
from src.contracts.attribution import (
    AgentResearchSummary,
    EventPipelineOutcome,
    FinancialAttributionComponent,
    ForecastLayerComparison,
    MonthlyScenarioDelta,
    NoSignalExplanation,
    RejectedEventCandidateSummary,
    ResearchFunnel,
    ResearchResultSummary,
    RetryMetadata,
    SectionStatusSummary,
    ValidationFailureDetail,
)
from src.contracts.financial import FinancialScenarioResult
from src.contracts.forecast import ForecastStatus
from src.contracts.official import OfficialDataBundle, OfficialDataRequest, OfficialDataStatus
from src.contracts.research import AgentType, ResearchRequest
from src.contracts.store import StoreProfile
from src.finance.monthly_scenario import run_monthly_financial_scenario
from src.forecasting.pipeline import BaselineForecastPipeline
from src.forecasting.official_features import OfficialFeatureBuilder
from src.orchestration.official_data_pipeline import OfficialDataPipeline
from src.orchestration.research_pipeline import ResearchPipeline, ResearchPipelineResult
from src.operations.metrics import metrics
from src.registries.event_registry import default_registry
from src.relief.pipeline import EligibilityAndBenefitPipeline, build_policy_search_context
from src.reporting.deterministic_report import DeterministicReportPayload, render_deterministic_report
from src.reporting.grounded_summary import build_grounded_summary
from src.source_snapshot.bok import assess_bok_monetary_policy_content
from src.signals.monthly_builder import MonthlySignalBuilder
from src.storage.analysis_repository import AnalysisResultRepository, ScenarioResultRepository


@dataclass
class AnalysisExecution:
    result: AnalysisResultV1
    report: DeterministicReportPayload | None
    research: ResearchPipelineResult


def _git_output(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=5,
        )
        return completed.stdout or ""
    except Exception:
        return ""


def _run_provenance(configuration: dict[str, object]) -> dict[str, object]:
    commit = _git_output("rev-parse", "HEAD").strip() or "unknown"
    status = _git_output("status", "--porcelain=v1", "--untracked-files=all")
    diff = _git_output("diff", "--binary", "HEAD", "--")
    untracked = sorted(filter(None, _git_output(
        "ls-files", "--others", "--exclude-standard"
    ).splitlines()))
    manifest = []
    for path in untracked:
        object_hash = _git_output("hash-object", "--no-filters", "--", path).strip()
        manifest.append({"path": path.replace("\\", "/"), "object_hash": object_hash})
    canonical_manifest = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    canonical_configuration = json.dumps(
        configuration, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return {
        "git_commit": commit,
        "git_dirty": bool(status.strip()),
        "working_tree_diff_hash": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "untracked_file_manifest_hash": hashlib.sha256(canonical_manifest).hexdigest(),
        "configuration_fingerprint": hashlib.sha256(
            canonical_configuration
        ).hexdigest(),
    }


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=2
        ).stdout.strip()
    except Exception:
        return "unknown"


def _section_map() -> dict[AnalysisSection, SectionExecution]:
    return {section: SectionExecution() for section in AnalysisSection}


def _synthetic_replay_context(documents: dict[str, object]) -> EvidenceReplayContext | None:
    """Expose an unambiguous non-live label only for fully synthetic replays."""
    values = list(documents.values())
    if not values:
        return None
    if any(
        getattr(document, "http_metadata", {}).get("x-synthetic-demo") != "true"
        for document in values
    ):
        return None
    fixture_ids = {
        str(getattr(document, "http_metadata", {}).get("x-demo-dataset-id") or "")
        for document in values
    }
    if len(fixture_ids) != 1 or not next(iter(fixture_ids)):
        return None
    return EvidenceReplayContext(
        mode="SYNTHETIC_DEMO_REPLAY",
        fixture_id=next(iter(fixture_ids)),
        captured_from="network-disabled synthetic demo dataset",
        source_urls=sorted({str(getattr(document, "canonical_url", "")) for document in values}),
        notice="Synthetic demo data only; this is not live evidence or current research.",
    )


def _finish(
    sections: dict[AnalysisSection, SectionExecution],
    section: AnalysisSection,
    status: SectionStatus,
    output: object | None = None,
    failures: list[str] | None = None,
    warnings: list[str] | None = None,
    count: int = 0,
) -> None:
    current = sections[section]
    current.status = status
    current.completed_at = datetime.now(UTC)
    current.failure_codes = failures or []
    current.warnings = warnings or []
    current.record_count = count
    current.output_hash = canonical_json_hash(output) if output is not None else None


def _start(sections: dict[AnalysisSection, SectionExecution], section: AnalysisSection, value: object) -> None:
    current = sections[section]
    current.status = SectionStatus.RUNNING
    current.started_at = datetime.now(UTC)
    current.input_hash = canonical_json_hash(value)

_FAILURE_MESSAGES = {
    "DATE_PARSE_FAILED": "The candidate date could not be normalized deterministically.",
    "QUOTE_NOT_FOUND": "The evidence quotation was not found in the stored source revision.",
    "OFFSET_MISMATCH": "The evidence offsets did not match the stored source revision.",
    "SOURCE_UNAVAILABLE": "The cited source revision was unavailable.",
    "SOURCE_UNTRUSTED": "The source did not meet the configured source-tier rule.",
    "FORECAST_WINDOW_NOT_OVERLAPPED": "The event did not overlap the forecast window.",
    "OUTSIDE_SEARCH_RADIUS": "The event was outside the configured store search radius.",
    "INDUSTRY_NOT_RELEVANT": "The event was not relevant to the store industry.",
    "MISSING_REQUIRED_FIELD": "A registry-required field was missing.",
    "ENUM_NOT_ALLOWED": "The candidate used a value not allowed by the event registry.",
}


def _failure_details(codes: list[str], retryable: bool) -> list[ValidationFailureDetail]:
    return [
        ValidationFailureDetail(
            code=code,
            message=_FAILURE_MESSAGES.get(code, code.replace("_", " ").title()),
            retryable=retryable,
        )
        for code in codes
    ]


def _research_summary(
    core: ResearchPipelineResult,
    policy: ResearchPipelineResult,
    signals: list,
    store: StoreProfile,
) -> ResearchResultSummary:
    registry = default_registry()
    rejected: list[RejectedEventCandidateSummary] = []
    for outcome in core.rejected_events:
        candidate = outcome.candidate
        signal_enabled, signal_reason = registry.signal_eligibility(str(candidate.event_type))
        rejected.append(RejectedEventCandidateSummary(
            candidate_id=candidate.candidate_id,
            status=outcome.status,
            failure_codes=outcome.failure_codes,
            failure_details=_failure_details(outcome.failure_codes, outcome.retryable),
            domain=str(candidate.domain),
            event_family=candidate.event_family,
            event_type=str(candidate.event_type),
            title=candidate.title,
            actor_org_raw=candidate.actor_org_raw,
            target_subject_raw=candidate.target_subject_raw,
            temporal=candidate.temporal,
            location=candidate.location,
            affected_industries_raw=candidate.affected_industries_raw,
            impacts=candidate.impacts,
            evidence=candidate.evidence,
            source_ids=sorted({item.source_id for item in candidate.evidence}),
            source_revision_ids=sorted({item.source_revision_id for item in candidate.evidence}),
            signal_enabled=False,
            event_type_signal_enabled=signal_enabled,
            candidate_signal_eligible=False,
            signal_eligibility_reason=(
                signal_reason if not signal_enabled else
                _FAILURE_MESSAGES.get(
                    outcome.failure_codes[0], outcome.failure_codes[0].replace("_", " ").title()
                ) if outcome.failure_codes else "Instance validation failed."
            ),
            validation_metadata=outcome.validation_metadata,
            lifecycle_stages=outcome.lifecycle_stages,
            primary_exclusion_reason=(outcome.failure_codes[0] if outcome.failure_codes else None),
            expected_impact_if_unblocked=(
                "The event could affect " + ", ".join(sorted({str(item.axis).split(".")[-1] for item in candidate.impacts}))
                + " if the exclusion condition were removed."
            ),
            retry=RetryMetadata(
                attempted=outcome.retry_attempted,
                outcome=outcome.retry_outcome,
                candidate_id=outcome.retry_candidate_id,
            ),
        ))

    reference_by_key = {}
    for finding in [*core.findings, *policy.findings]:
        normalized_title = re.sub(
            r"\s+", " ", unicodedata.normalize("NFKC", finding.title)
        ).strip().casefold()
        key = (
            ("BOK_DECISION", finding.finding_id, "")
            if finding.reason_code == "BOK_RATE_HOLD_REFERENCE_ONLY"
            else (
                "GENERAL",
                "|".join(sorted(finding.source_revision_ids)),
                f"{finding.reason_code}|{normalized_title}",
            )
        )
        existing = reference_by_key.get(key)
        if existing is None:
            reference_by_key[key] = finding
        else:
            evidence = {
                item.evidence_id: item
                for item in [*existing.evidence, *finding.evidence]
            }
            reference_by_key[key] = existing.model_copy(update={
                "source_ids": sorted({*existing.source_ids, *finding.source_ids}),
                "source_revision_ids": sorted({
                    *existing.source_revision_ids, *finding.source_revision_ids
                }),
                "evidence": [evidence[item] for item in sorted(evidence)],
            })
    reference_findings = [reference_by_key[key] for key in sorted(reference_by_key)]
    risk_bundles = core.bundles
    all_bundles = core.bundles + policy.bundles
    risk_outcomes = [outcome for bundle in risk_bundles for outcome in bundle.document_outcomes]
    # Routing can add detail pages and attachments after the discovery list has
    # been recorded.  Count both totals from the same unique source-ID set so a
    # traversed source cannot make the usable-document ratio exceed one.
    risk_document_ids = {
        source_id for item in risk_bundles for source_id in item.source_document_ids
    } | {outcome.source_id for outcome in risk_outcomes}
    risk_usable_document_ids = {
        outcome.source_id for outcome in risk_outcomes if outcome.usable_for_extraction
    }
    risk_document_count = len(risk_document_ids)
    risk_usable_count = len(risk_usable_document_ids)
    risk_navigation_count = sum(
        1 for outcome in risk_outcomes if "NAVIGATION_ONLY" in outcome.reason_codes
    )
    accepted_candidate_ids = [
        candidate_id for event in core.accepted_events for candidate_id in event.candidate_ids
    ]
    rejected_candidate_ids = [
        outcome.candidate.candidate_id for outcome in core.rejected_events
    ]
    if len(accepted_candidate_ids) != len(set(accepted_candidate_ids)):
        raise ValueError("duplicate accepted event candidate IDs")
    if len(rejected_candidate_ids) != len(set(rejected_candidate_ids)):
        raise ValueError("duplicate rejected event candidate IDs")
    if set(accepted_candidate_ids).intersection(rejected_candidate_ids):
        raise ValueError("candidate ID has both accepted and rejected outcomes")
    risk_candidate_count = len(accepted_candidate_ids) + len(rejected_candidate_ids)
    risk_extraction_tokens = sum(
        record.input_tokens for item in risk_bundles for record in item.model_call_records
        if record.prompt_version != "search_query.v1"
    )
    funnel = ResearchFunnel(
        query_count=sum(len(item.search_queries) for item in risk_bundles),
        discovery_hit_count=sum(int(item.metadata.get("discovery_hit_count") or 0) for item in risk_bundles),
        document_count=risk_document_count,
        fetched_document_count=sum(
            item.diagnostics.fetched_document_count for item in risk_bundles
        ),
        resolved_source_count=sum(int(item.metadata.get("resolved_source_count") or 0) for item in risk_bundles),
        usable_document_count=risk_usable_count,
        access_failure_count=sum(len(item.access_failures) for item in risk_bundles),
        navigation_only_count=sum(
            1 for outcome in risk_outcomes if "NAVIGATION_ONLY" in outcome.reason_codes
        ),
        duplicate_document_count=sum(
            int(item.metadata.get("deduplicated_document_count") or 0) for item in risk_bundles
        ),
        reference_finding_count=len(reference_findings),
        candidate_count=risk_candidate_count,
        rejected_candidate_count=len(rejected_candidate_ids),
        accepted_event_count=len(accepted_candidate_ids),
        signal_eligible_event_count=sum(1 for event in core.accepted_events if event.signal_enabled),
        applied_signal_count=sum(signal.raw_signal != 0 for signal in signals),
        provider_failure_count=sum(len(item.provider_failures) for item in risk_bundles),
        operation_timeout_count=sum(
            sum(item.diagnostics.operation_timeout_counts.values()) for item in risk_bundles
        ),
        timeout_agent_count=sum(
            1 for item in risk_bundles if item.diagnostics.timeout_stage is not None
        ),
        usable_document_ratio=(risk_usable_count / risk_document_count if risk_document_count else 0),
        navigation_only_ratio=(risk_navigation_count / risk_document_count if risk_document_count else 0),
        extraction_tokens_per_usable_candidate=(
            risk_extraction_tokens / risk_candidate_count if risk_candidate_count else None
        ),
    )
    agent_summaries = []
    for bundle in all_bundles:
        agent_code = str(bundle.agent_type).split(".")[-1]
        finding_count = sum(
            1 for finding in [*core.findings, *policy.findings]
            if str(finding.agent_type).split(".")[-1] == agent_code
        )
        agent_summaries.append(AgentResearchSummary(
            agent_type=agent_code,
            category="POLICY" if agent_code == "POLICY_REGULATION" else "RISK_RESEARCH",
            status=str(bundle.status).split(".")[-1],
            query_count=len(bundle.search_queries),
            document_count=len(set(bundle.source_document_ids)),
            usable_document_count=int(bundle.metadata.get("usable_document_count") or 0),
            discovered_hit_count=bundle.diagnostics.discovered_hit_count,
            fetched_document_count=bundle.diagnostics.fetched_document_count,
            finding_count=finding_count,
            provider_failure_count=len(bundle.provider_failures),
            deduplicated_document_count=int(bundle.metadata.get("deduplicated_document_count") or 0),
            extraction_tokens_per_usable_candidate=bundle.metadata.get("extraction_tokens_per_usable_candidate"),
            candidate_count=(
                len(bundle.policy_candidate_ids)
                if agent_code == "POLICY_REGULATION"
                else len(bundle.event_candidate_ids)
            ),
            access_failure_count=len(bundle.access_failures),
            model_call_count=len(bundle.model_call_records),
            no_result_reasons=bundle.no_result_reasons,
            providers=sorted({record.provider for record in bundle.model_call_records}),
            models=sorted({record.model for record in bundle.model_call_records}),
            timeout_stage=bundle.diagnostics.timeout_stage,
            operation_timeout_counts=bundle.diagnostics.operation_timeout_counts,
            partial_output_counts=bundle.diagnostics.partial_output_counts,
            configured_limits=bundle.diagnostics.configured_limits,
            elapsed_time_ms_by_stage=bundle.diagnostics.elapsed_time_ms_by_stage,
            skipped_counts=bundle.diagnostics.skipped_counts,
            total_latency_ms=sum(record.latency_ms for record in bundle.model_call_records),
            input_tokens=sum(record.input_tokens for record in bundle.model_call_records),
            output_tokens=sum(record.output_tokens for record in bundle.model_call_records),
        ))
    event_pipeline_outcomes: list[EventPipelineOutcome] = []
    signals_by_event: dict[str, list] = {}
    for signal in signals:
        signals_by_event.setdefault(signal.event_id, []).append(signal)
    has_variable_debt = (
        store.cost_exposures.variable_rate_debt_share > 0
        and any(loan.rate_type == "VARIABLE" for loan in store.loans)
    )
    for event in core.accepted_events:
        event_signals = signals_by_event.get(event.event_id, [])
        stages = [
            "DISCOVERED", "EXTRACTED", "VALIDATION_ATTEMPTED", "EVIDENCE_VALIDATED",
            "TEMPORAL_VALIDATED", "GEO_VALIDATED",
        ]
        interest_only = all(str(impact.axis).split(".")[-1] == "INTEREST_COST" for impact in event.impacts)
        exposure_relevance = (
            "NO_VARIABLE_RATE_DEBT_EXPOSURE" if interest_only and not has_variable_debt
            else "RELEVANT"
        )
        if not event.signal_enabled:
            stages.append("VALIDATED_REFERENCE_ONLY")
            terminal = "VALIDATED_REFERENCE_ONLY"
            exclusion = "SIGNAL_DISABLED_EVENT_TYPE"
        else:
            stages.append("INSTANCE_ELIGIBLE")
            terminal = "INSTANCE_ELIGIBLE"
            exclusion = None
        if event.signal_enabled and event_signals:
            stages.append("SIGNAL_GENERATED")
            terminal = "SIGNAL_GENERATED"
            if any(signal.raw_signal != 0 for signal in event_signals):
                stages.append("FINANCIALLY_APPLIED")
                terminal = "FINANCIALLY_APPLIED"
            else:
                exclusion = exposure_relevance
        for candidate_id in event.candidate_ids:
            event_pipeline_outcomes.append(EventPipelineOutcome(
                event_id=event.event_id,
                candidate_id=candidate_id,
                title=event.title,
                lifecycle_stages=stages,
                terminal_status=terminal,
                primary_exclusion_reason=exclusion,
                signal_eligible=event.signal_enabled,
                event_type_signal_enabled=event.signal_enabled,
                candidate_signal_eligible=event.signal_enabled,
                store_distance_meters=event.location.distance_meters,
                configured_radius_meters=event.location.resolution_metadata.get("configured_radius_meters"),
                financial_exposure_relevance=exposure_relevance,
                expected_impact_if_unblocked=(
                    "Interest impact remains zero until variable-rate debt exposure exists."
                    if exposure_relevance == "NO_VARIABLE_RATE_DEBT_EXPOSURE"
                    else "Eligible impacts flow into the store scenario when all validation and exposure gates pass."
                ),
                signal_ids=[signal.signal_id for signal in event_signals],
            ))
    for item in rejected:
        metadata = item.validation_metadata
        excluded_by_distance = "OUTSIDE_SEARCH_RADIUS" in item.failure_codes
        terminal = "EXCLUDED_BY_DISTANCE" if excluded_by_distance else item.status
        stages = list(item.lifecycle_stages)
        if excluded_by_distance and "EXCLUDED_BY_DISTANCE" not in stages:
            stages.append("EXCLUDED_BY_DISTANCE")
        event_pipeline_outcomes.append(EventPipelineOutcome(
            candidate_id=item.candidate_id,
            title=item.title or item.candidate_id,
            lifecycle_stages=stages,
            terminal_status=terminal,
            primary_exclusion_reason=("OUTSIDE_SEARCH_RADIUS" if excluded_by_distance else item.primary_exclusion_reason),
            signal_eligible=item.signal_enabled,
            store_distance_meters=metadata.get("distance_meters"),
            event_type_signal_enabled=item.event_type_signal_enabled,
            candidate_signal_eligible=False,
            configured_radius_meters=metadata.get("configured_radius_meters"),
            financial_exposure_relevance="NOT_EVALUATED_DUE_TO_VALIDATION_GATE",
            expected_impact_if_unblocked=item.expected_impact_if_unblocked or "No financial impact is applied while the validation gate is blocked.",
        ))

    explanation = None
    if not signals:
        facts = [
            f"{funnel.query_count} searches produced {funnel.document_count} documents and {funnel.candidate_count} candidates.",
            f"{funnel.accepted_event_count} events were validated and {funnel.signal_eligible_event_count} were signal-eligible.",
        ]
        reason_codes = ["NO_VALIDATED_SIGNAL_ELIGIBLE_EVENT"]
        if rejected:
            codes = sorted({code for item in rejected for code in item.failure_codes})
            facts.append(f"Candidate validation reported: {', '.join(codes)}.")
            reason_codes.extend(codes)
        disabled = sorted({item.event_type for item in rejected if item.event_type and not item.signal_enabled})
        if disabled:
            facts.append(f"Signal-disabled registry rules applied to: {', '.join(disabled)}.")
            reason_codes.append("SIGNAL_DISABLED_EVENT_TYPE")
        if funnel.access_failure_count:
            facts.append(f"{funnel.access_failure_count} source documents could not be accessed.")
            reason_codes.append("SOURCE_ACCESS_FAILURES")
        explanation = NoSignalExplanation(
            headline="No financial AI signals were applied.",
            reason_codes=sorted(set(reason_codes)),
            facts=facts,
            limitation="No applied signal does not mean that no real-world risk exists; it means no validated, eligible signal was available to this run.",
        )
    return ResearchResultSummary(
        bundles=all_bundles,
        accepted_events=core.accepted_events,
        rejected_events=rejected,
        reference_findings=reference_findings,
        event_pipeline_outcomes=event_pipeline_outcomes,
        errors=core.errors + policy.errors,
        risk_status=(
            "PARTIAL" if core.errors or any(
                str(bundle.status).split(".")[-1] == "PARTIAL" for bundle in core.bundles
            ) else "COMPLETED"
        ),
        policy_status=(
            "PARTIAL" if policy.errors or any(
                str(bundle.status).split(".")[-1] == "PARTIAL" for bundle in policy.bundles
            ) else "COMPLETED"
        ),
        funnel=funnel,
        agent_summaries=agent_summaries,
        no_signal_explanation=explanation,
    )


def _forecast_comparison(
    comparison_id: str,
    base_layer: str,
    comparison_layer: str,
    base: FinancialScenarioResult,
    comparison: FinancialScenarioResult,
    source_feature_set_id: str | None = None,
) -> ForecastLayerComparison:
    base_by_month = {item.month_str: item for item in base.monthly_cash_flows}
    comparison_by_month = {item.month_str: item for item in comparison.monthly_cash_flows}
    months: list[MonthlyScenarioDelta] = []
    for month in sorted(set(base_by_month) & set(comparison_by_month)):
        left = base_by_month[month]
        right = comparison_by_month[month]
        months.append(MonthlyScenarioDelta(
            month=month,
            base_revenue_cash_krw=left.revenue_cash_krw,
            comparison_revenue_cash_krw=right.revenue_cash_krw,
            revenue_cash_delta_krw=right.revenue_cash_krw-left.revenue_cash_krw,
            base_ingredient_cost_krw=left.ingredient_costs_cash_krw,
            comparison_ingredient_cost_krw=right.ingredient_costs_cash_krw,
            ingredient_cost_delta_krw=right.ingredient_costs_cash_krw-left.ingredient_costs_cash_krw,
            ingredient_cost_savings_krw=left.ingredient_costs_cash_krw-right.ingredient_costs_cash_krw,
            base_interest_payment_krw=left.interest_payment_krw,
            comparison_interest_payment_krw=right.interest_payment_krw,
            interest_payment_delta_krw=right.interest_payment_krw-left.interest_payment_krw,
            base_net_cash_flow_krw=left.net_cash_flow_krw,
            comparison_net_cash_flow_krw=right.net_cash_flow_krw,
            net_cash_flow_delta_krw=right.net_cash_flow_krw-left.net_cash_flow_krw,
            base_ending_cash_krw=left.ending_cash_krw,
            comparison_ending_cash_krw=right.ending_cash_krw,
            ending_cash_delta_krw=right.ending_cash_krw-left.ending_cash_krw,
        ))
    pairs = [(base_by_month[item.month], comparison_by_month[item.month]) for item in months]
    components = [
        FinancialAttributionComponent(component="REVENUE", label="Revenue adjustment", signed_cash_effect_krw=sum((right.revenue_cash_krw-left.revenue_cash_krw for left, right in pairs), Decimal("0"))),
        FinancialAttributionComponent(component="INGREDIENT_COST", label="Ingredient cost adjustment", signed_cash_effect_krw=sum((left.ingredient_costs_cash_krw-right.ingredient_costs_cash_krw for left, right in pairs), Decimal("0"))),
        FinancialAttributionComponent(component="OTHER_VARIABLE_COST", label="Other variable cost adjustment", signed_cash_effect_krw=sum((left.other_variable_costs_cash_krw-right.other_variable_costs_cash_krw for left, right in pairs), Decimal("0"))),
        FinancialAttributionComponent(component="FIXED_COST", label="Fixed cost adjustment", signed_cash_effect_krw=sum((left.fixed_costs_cash_krw-right.fixed_costs_cash_krw for left, right in pairs), Decimal("0"))),
        FinancialAttributionComponent(component="INTEREST", label="Interest adjustment", signed_cash_effect_krw=sum((left.interest_payment_krw-right.interest_payment_krw for left, right in pairs), Decimal("0"))),
        FinancialAttributionComponent(component="PRINCIPAL", label="Principal adjustment", signed_cash_effect_krw=sum((left.principal_payment_krw-right.principal_payment_krw for left, right in pairs), Decimal("0"))),
        FinancialAttributionComponent(component="TAX", label="Tax adjustment", signed_cash_effect_krw=sum((left.tax_cash_outflow_krw-right.tax_cash_outflow_krw for left, right in pairs), Decimal("0"))),
        FinancialAttributionComponent(component="CAPEX", label="Capital expenditure adjustment", signed_cash_effect_krw=sum((left.capital_expenditure_krw-right.capital_expenditure_krw for left, right in pairs), Decimal("0"))),
        FinancialAttributionComponent(component="OTHER_INFLOW", label="Other cash inflow adjustment", signed_cash_effect_krw=sum((right.other_cash_inflows_krw-left.other_cash_inflows_krw for left, right in pairs), Decimal("0"))),
    ]
    ending_delta = months[-1].ending_cash_delta_krw if months else Decimal("0")
    return ForecastLayerComparison(
        comparison_id=comparison_id,
        base_layer=base_layer,
        comparison_layer=comparison_layer,
        monthly_deltas=months,
        ending_cash_delta_krw=ending_delta,
        attribution=components,
        source_feature_set_id=source_feature_set_id,
        event_ids=sorted(filter(None, comparison.metadata.get("event_ids", "").split(","))),
        signal_ids=sorted(filter(None, comparison.metadata.get("signal_ids", "").split(","))),
        base_scenario_id=base.metadata.get("scenario_id"),
        comparison_scenario_id=comparison.metadata.get("scenario_id"),
    )


def _official_diagnostics(official) -> list[str]:
    diagnostics: list[str] = []
    for item in official.collection_results:
        if str(item.status).split(".")[-1] == "COMPLETED":
            continue
        kind = "REQUIRED_OFFICIAL_INDICATOR_MISSING" if item.required else "OPTIONAL_OFFICIAL_INDICATOR_MISSING"
        diagnostics.append(f"{kind}: provider={item.provider}; indicator={item.indicator_id}; reason={item.failure_code or 'NO_OBSERVATIONS'}")
    return diagnostics


def _cross_validate_bok_reference_findings(
    research: ResearchPipelineResult,
    official: OfficialDataBundle,
) -> None:
    """Quarantine BOK references that conflict with an available ECOS value."""
    observations = [
        item for item in official.observations
        if item.indicator_id == "BASE_RATE"
        and item.observed_at <= official.as_of_date
        and str(item.quality_status).split(".")[-1] not in {"REJECTED", "STALE"}
    ]
    if not observations:
        return
    latest = max(
        observations,
        key=lambda item: (item.observed_at, item.available_at, item.observation_id),
    )
    conflicted_sources: set[str] = set()
    retained = []
    for finding in research.findings:
        if finding.reason_code != "BOK_RATE_HOLD_REFERENCE_ONLY":
            retained.append(finding)
            continue
        document = next((
            research.documents.get(source_id)
            for source_id in finding.source_ids
            if source_id in research.documents
        ), None)
        assessment = (
            assess_bok_monetary_policy_content(
                document, official_rate_percent=latest.value,
            )
            if document is not None else None
        )
        if assessment and "BOK_RATE_OFFICIAL_DATA_CONFLICT" in assessment.reason_codes:
            conflicted_sources.update(finding.source_ids)
            continue
        retained.append(finding)
    research.findings = retained
    if not conflicted_sources:
        return
    for bundle in research.bundles:
        for outcome in bundle.document_outcomes:
            if outcome.source_id in conflicted_sources:
                outcome.reason_codes = list(dict.fromkeys([
                    *outcome.reason_codes, "BOK_RATE_OFFICIAL_DATA_CONFLICT",
                ]))
        bundle.metadata.setdefault("reference_rejection_diagnostics", []).append({
            "reason_code": "BOK_RATE_OFFICIAL_DATA_CONFLICT",
            "source_ids": sorted(conflicted_sources),
            "official_observation_id": latest.observation_id,
        })


def _section_summaries(sections: dict[AnalysisSection, SectionExecution]) -> list[SectionStatusSummary]:
    labels = {
        AnalysisSection.OFFICIAL_DATA: ("Official data", "Controls which official observations and projected model inputs were applied."),
        AnalysisSection.RESEARCH: ("Risk research", "Controls validated external event evidence; policy extraction is reported separately."),
        AnalysisSection.SIGNALS: ("Signals", "Controls whether validated, eligible events adjust financial scenarios."),
        AnalysisSection.FINANCE: ("Finance", "Controls forecast cash-flow, break-even, and layer comparison availability."),
        AnalysisSection.POLICIES: ("Policies", "Controls policy candidates only; it does not change risk-research status."),
    }
    return [SectionStatusSummary(
        section=str(section),
        label=label,
        status=str(sections[section].status),
        record_count=sections[section].record_count,
        warnings=sections[section].warnings,
        failure_codes=sections[section].failure_codes,
        started_at=sections[section].started_at,
        completed_at=sections[section].completed_at,
        effect=effect,
    ) for section, (label, effect) in labels.items()]


class AnalysisOrchestrator:
    def __init__(
        self,
        research_pipeline: ResearchPipeline,
        official_pipeline: OfficialDataPipeline,
        forecast_pipeline: BaselineForecastPipeline,
        result_repository: AnalysisResultRepository,
        scenario_repository: ScenarioResultRepository,
    ):
        self.research_pipeline = research_pipeline
        self.official_pipeline = official_pipeline
        self.forecast_pipeline = forecast_pipeline
        self.result_repository = result_repository
        self.scenario_repository = scenario_repository
        self.signal_builder = MonthlySignalBuilder()
        self.policy_pipeline = EligibilityAndBenefitPipeline()
        self.official_feature_builder = OfficialFeatureBuilder()

    def _research_subset(self, policy: bool) -> ResearchPipeline:
        agents = [
            agent for agent in self.research_pipeline.agents
            if (agent.agent_type == AgentType.POLICY_REGULATION) == policy
        ]
        return ResearchPipeline(
            agents,
            self.research_pipeline.validator,
            self.research_pipeline.event_repo,
            self.research_pipeline.policy_repo,
            self.research_pipeline.audit_repo,
        )

    def run(
        self,
        store: StoreProfile,
        request: ResearchRequest,
        official_requests: list[OfficialDataRequest] | None = None,
        idempotency_key: str | None = None,
    ) -> AnalysisExecution:
        idempotency_key = idempotency_key or canonical_json_hash({
            "store": store.model_dump(mode="json"),
            "request": request.model_dump(mode="json"),
            "official_requests": [item.model_dump(mode="json") for item in (official_requests or [])],
        })
        existing = self.result_repository.get_by_idempotency_key(idempotency_key, request.tenant_id)
        if existing:
            empty_research = ResearchPipelineResult(run_id=request.run_id)
            return AnalysisExecution(existing, self._report_from_result(store, existing), empty_research)

        created_at = datetime.now(UTC)
        sections = _section_map()
        warnings: list[str] = []
        limitations = [
            "Forecast intervals and policy effects are decision-support estimates, not guarantees.",
            "Policy availability and final eligibility require confirmation by the official provider.",
        ]
        input_snapshot = {
            "store_profile": store.model_dump(mode="json"),
            "research_request": request.model_dump(mode="json"),
            "official_requests": [item.model_dump(mode="json") for item in (official_requests or [])],
        }
        _start(sections, AnalysisSection.INPUT, input_snapshot)
        _finish(sections, AnalysisSection.INPUT, SectionStatus.COMPLETED, input_snapshot, count=1)

        _start(sections, AnalysisSection.OFFICIAL_DATA, official_requests or [])
        official = self.official_pipeline.run(request.run_id, request.as_of_date, official_requests or [])
        official_section_status = {
            OfficialDataStatus.COMPLETED: SectionStatus.COMPLETED,
            OfficialDataStatus.PARTIAL: SectionStatus.PARTIAL,
            OfficialDataStatus.FAILED: SectionStatus.FAILED,
            OfficialDataStatus.SKIPPED: SectionStatus.SKIPPED,
        }[OfficialDataStatus(official.status)]
        _finish(
            sections, AnalysisSection.OFFICIAL_DATA, official_section_status, official,
            failures=list(official.provider_errors.values()) if official.status == OfficialDataStatus.FAILED else [],
            warnings=_official_diagnostics(official) if official.status == OfficialDataStatus.PARTIAL else [],
            count=len(official.observations),
        )

        _start(sections, AnalysisSection.RESEARCH, request)
        core_pipeline = self._research_subset(policy=False)
        official_indicator_ids = sorted({item.indicator_id for item in official.observations})
        research_request = request.model_copy(update={
            "official_indicator_snapshot_ids": sorted(set(
                request.official_indicator_snapshot_ids + official_indicator_ids
            )),
        })
        core_research = (
            core_pipeline.run(research_request)
            if core_pipeline.agents else ResearchPipelineResult(run_id=request.run_id)
        )
        _cross_validate_bok_reference_findings(core_research, official)
        research_status = SectionStatus.PARTIAL if core_research.errors or any(
            str(bundle.status).split(".")[-1] == "PARTIAL" for bundle in core_research.bundles
        ) else SectionStatus.COMPLETED
        _finish(
            sections, AnalysisSection.RESEARCH, research_status,
            {"events": core_research.accepted_events, "errors": core_research.errors},
            warnings=core_research.errors, count=len(core_research.accepted_events),
        )

        official_features = self.official_feature_builder.build(
            official,
            request.forecast_start,
            store.forecast_horizon_months,
            official_events=core_research.accepted_events,
        )
        _start(sections, AnalysisSection.BASELINE, store.monthly_history)
        trend_baseline = self.forecast_pipeline.run(
            request.run_id, store, request.forecast_start
        )
        baseline = self.forecast_pipeline.run(
            request.run_id,
            store,
            request.forecast_start,
            [official.snapshot_id] if official.observations else [],
            official_features,
        )
        baseline_status = (
            SectionStatus.COMPLETED if baseline.status == ForecastStatus.COMPLETED else
            SectionStatus.PARTIAL if baseline.status == ForecastStatus.PARTIAL else
            SectionStatus.FAILED
        )
        _finish(
            sections,
            AnalysisSection.BASELINE,
            baseline_status,
            {"trend": trend_baseline, "official": baseline},
            failures=[str(baseline.status)] if baseline_status == SectionStatus.FAILED else [],
            warnings=[baseline.fallback_reason] if baseline.fallback_reason and baseline_status != SectionStatus.FAILED else [],
            count=len(baseline.monthly_forecasts),
        )

        signals = []
        adjustments = {}
        scenarios = {}
        finance_error: str | None = None
        trend_scenario = None
        if baseline.monthly_forecasts:
            _start(sections, AnalysisSection.SIGNALS, core_research.accepted_events)
            signals, adjustments = self.signal_builder.build(
                core_research.accepted_events, store, request.forecast_start, len(baseline.monthly_forecasts)
            )
            self.research_pipeline.event_repo.save_signals(request.run_id, signals)
            _finish(sections, AnalysisSection.SIGNALS, SectionStatus.COMPLETED, adjustments, count=len(signals))
            _start(sections, AnalysisSection.FINANCE, {"baseline": baseline, "adjustments": adjustments})
            try:
                trend_scenario = run_monthly_financial_scenario(
                    store,
                    trend_baseline,
                    adjustments["BASELINE"],
                    official_features=None,
                )
                self.scenario_repository.save(
                    request.run_id,
                    trend_scenario.metadata["scenario_id"],
                    trend_baseline.forecast_id,
                    adjustments["BASELINE"].adjustment_id,
                    trend_scenario.model_dump(mode="json"),
                )
                for name, adjustment in adjustments.items():
                    scenario_started = time.perf_counter()
                    try:
                        scenario = run_monthly_financial_scenario(
                            store,
                            baseline,
                            adjustment,
                            official_features=official_features,
                        )
                    finally:
                        metrics.observe(
                            "scenario_calculation_latency_ms",
                            (time.perf_counter() - scenario_started) * 1000,
                        )
                    scenarios[name] = scenario
                    scenario_id = scenario.metadata["scenario_id"]
                    self.scenario_repository.save(
                        request.run_id, scenario_id, baseline.forecast_id,
                        adjustment.adjustment_id, scenario.model_dump(mode="json"),
                    )
                _finish(
                    sections,
                    AnalysisSection.FINANCE,
                    SectionStatus.COMPLETED,
                    {"trend": trend_scenario, "official_and_ai": scenarios},
                    count=len(scenarios) + 1,
                )
            except Exception as exc:
                finance_error = f"{type(exc).__name__}: {exc}"
                _finish(sections, AnalysisSection.FINANCE, SectionStatus.FAILED, failures=[finance_error])
        else:
            _finish(sections, AnalysisSection.SIGNALS, SectionStatus.SKIPPED, warnings=["No baseline forecast"])
            _finish(sections, AnalysisSection.FINANCE, SectionStatus.SKIPPED, warnings=["No baseline forecast"])

        _start(sections, AnalysisSection.POLICIES, scenarios.get("BASELINE", {}))
        policy_agents = self._research_subset(policy=True)
        policy_research = ResearchPipelineResult(run_id=request.run_id)
        if "BASELINE" not in scenarios:
            context = PolicySearchContext(
                business_type_code=store.business_type_code,
                region_codes=request.administrative_area_codes,
            )
            policies = PolicyResultBundle(search_context=context)
            _finish(sections, AnalysisSection.POLICIES, SectionStatus.SKIPPED, warnings=["Finance result unavailable"])
        else:
            context = build_policy_search_context(store, scenarios["BASELINE"], request.administrative_area_codes)
            policy_request = request.model_copy(update={
                "policy_search_terms": context.purposes,
                "required_funding_krw": context.required_funding_krw,
                "projected_cash_burn_date": context.cash_burn_date,
            })
            policy_research = policy_agents.run(policy_request) if policy_agents.agents else ResearchPipelineResult(run_id=request.run_id)
            candidates = policy_research.policies
            policies = self.policy_pipeline.run(
                store, request.as_of_date, candidates, context, baseline,
                adjustments["BASELINE"], scenarios["BASELINE"], official_features,
            )
            policies = policies.model_copy(update={
                "reference_only_materials": policy_research.findings,
                "stage_counts": policies.stage_counts.model_copy(update={
                    "reference_only_materials": len(policy_research.findings),
                }),
            })
            policy_status = SectionStatus.PARTIAL if policy_research.errors or any(str(bundle.status).split(".")[-1] == "PARTIAL" for bundle in policy_research.bundles) else SectionStatus.COMPLETED
            _finish(
                sections, AnalysisSection.POLICIES, policy_status, policies,
                warnings=policy_research.errors, count=len(policies.candidates),
            )

        research_payload = _research_summary(core_research, policy_research, signals, store)
        source_ids = sorted(
            {source_id for event in core_research.accepted_events for source_id in event.source_ids}
            | {source_id for policy in policies.candidates for source_id in policy.source_ids}
            | {observation.source_id for observation in official.observations}
            | {source_id for item in research_payload.rejected_events for source_id in item.source_ids}
        )
        revision_ids = sorted(
            {revision_id for event in core_research.accepted_events for revision_id in event.source_revision_ids}
            | {observation.source_revision_id for observation in official.observations}
            | {revision_id for item in research_payload.rejected_events for revision_id in item.source_revision_ids}
        )
        traceability = TraceabilityManifest(
            source_ids=source_ids,
            source_revision_ids=revision_ids,
            official_snapshot_ids=[official.snapshot_id] if official.observations else [],
            official_observation_ids=sorted(item.observation_id for item in official.observations),
            event_ids=sorted(event.event_id for event in core_research.accepted_events),
            signal_ids=sorted(signal.signal_id for signal in signals),
            policy_ids=sorted(policy.policy_candidate_id for policy in policies.candidates),
            model_run_ids=sorted({trend_baseline.forecast_id, baseline.forecast_id}),
            scenario_ids=sorted(
                {item.metadata.get("scenario_id", name) for name, item in scenarios.items()}
                | ({trend_scenario.metadata["scenario_id"]} if trend_scenario else set())
            ),
            calculation_result_ids=sorted(
                {item.metadata.get("scenario_id", name) for name, item in scenarios.items()}
                | ({trend_scenario.metadata["scenario_id"]} if trend_scenario else set())
            ),
        )
        comparisons: list[ForecastLayerComparison] = []
        if trend_scenario and scenarios.get("BASELINE"):
            comparisons.append(_forecast_comparison(
                "CMP-TREND-OFFICIAL",
                "TREND",
                "OFFICIAL",
                trend_scenario,
                scenarios["BASELINE"],
                official_features.feature_set_id,
            ))
        for layer in ("LOW_IMPACT", "HIGH_IMPACT"):
            if scenarios.get("BASELINE") and scenarios.get(layer):
                comparisons.append(_forecast_comparison(
                    f"CMP-OFFICIAL-AI-{layer}",
                    "OFFICIAL",
                    f"AI_{layer}",
                    scenarios["BASELINE"],
                    scenarios[layer],
                    official_features.feature_set_id,
                ))
        prompt_versions: dict[str, str] = {}
        provider_models: dict[str, str] = {}
        for bundle in [*core_research.bundles, *policy_research.bundles]:
            for record in bundle.model_call_records:
                key = (
                    "SEARCH" if record.prompt_version == "search_query.v1"
                    else str(bundle.agent_type).split(".")[-1]
                )
                prompt_versions[key] = record.prompt_version
                provider_models[record.provider] = record.model
        provenance = _run_provenance({
            "event_registry_version": request.event_registry_version,
            "source_policy_version": request.source_policy_version,
            "forecast_start": request.forecast_start,
            "forecast_end": request.forecast_end,
            "as_of_date": request.as_of_date,
            "official_requests": [
                {
                    "provider": item.provider,
                    "indicator_id": item.indicator_id,
                    "required": item.required,
                    "max_age_days": item.max_age_days,
                }
                for item in (official_requests or [])
            ],
            "research_execution_limits": (
                {
                    "agent_wall_clock_limit_seconds": settings.research_agent_wall_clock_limit_seconds,
                    "search_request_timeout_seconds": settings.gemini_timeout_seconds,
                    "document_fetch_timeout_seconds": settings.http_timeout_seconds,
                    "extraction_request_timeout_seconds": settings.openai_timeout_seconds,
                    "analysis_job_timeout_seconds": settings.analysis_job_timeout_seconds,
                    "minimum_documents_after_discovery": settings.research_min_documents_after_discovery,
                    "official_seed_reserve": settings.research_official_seed_reserve,
                    "max_search_retries": settings.max_search_retries,
                    "max_extraction_retries": settings.max_extraction_retries,
                }
                if (settings := next(
                    (getattr(agent, "settings", None) for agent in self.research_pipeline.agents), None
                )) is not None
                else {}
            ),
        })
        versions = VersionManifest(
            event_registry_version=request.event_registry_version,
            source_policy_version=request.source_policy_version,
            forecast_model_versions={baseline.selected_model or "NONE": baseline.model_version or "NONE"},
            prompt_versions=prompt_versions,
            provider_models=provider_models,
            **provenance,
        )
        terminal_sections = [sections[item].status for item in (
            AnalysisSection.OFFICIAL_DATA,
            AnalysisSection.BASELINE,
            AnalysisSection.RESEARCH,
            AnalysisSection.FINANCE,
            AnalysisSection.POLICIES,
        )]
        if sections[AnalysisSection.FINANCE].status in {SectionStatus.FAILED, SectionStatus.SKIPPED}:
            overall_status = AnalysisRunStatus.FAILED
        elif any(status in {SectionStatus.PARTIAL, SectionStatus.FAILED} for status in terminal_sections):
            overall_status = AnalysisRunStatus.PARTIAL
        else:
            overall_status = AnalysisRunStatus.COMPLETED
        if finance_error:
            warnings.append(finance_error)
        if overall_status == AnalysisRunStatus.PARTIAL:
            # A partial result must be explainable at the top level; section
            # details remain available for traceability, but must not be the
            # only place a user can discover the incomplete stage.
            partial_sections = [
                section.value for section, execution in sections.items()
                if execution.status in {SectionStatus.PARTIAL, SectionStatus.FAILED}
            ]
            warnings.append(
                "PARTIAL_RESULT: incomplete sections="
                + (", ".join(partial_sections) if partial_sections else "UNKNOWN")
            )

        _start(sections, AnalysisSection.RESULT_ASSEMBLY, traceability)
        _finish(sections, AnalysisSection.RESULT_ASSEMBLY, SectionStatus.COMPLETED, {"run_id": request.run_id}, count=1)
        section_status_summary = _section_summaries(sections)
        result_version = self.result_repository.next_version(request.run_id, request.tenant_id)
        result_id = f"AR-{request.run_id}-V{result_version}"
        grounded_summary = build_grounded_summary(result_id, baseline, scenarios, traceability)
        evidence_replay = _synthetic_replay_context(core_research.documents)
        result = AnalysisResultV1(
            result_id=result_id,
            result_version=result_version,
            run_id=request.run_id,
            idempotency_key=idempotency_key,
            tenant_id=request.tenant_id,
            status=overall_status,
            created_at=created_at,
            completed_at=datetime.now(UTC),
            as_of_date=request.as_of_date,
            forecast_start=request.forecast_start,
            forecast_end=request.forecast_end,
            deterministic_hash="",
            sections=sections,
            input_snapshot=input_snapshot,
            official_data=official,
            official_features=official_features,
            trend_baseline=trend_baseline,
            trend_scenario=trend_scenario,
            baseline=baseline,
            research=research_payload,
            signals=signals,
            adjustments=adjustments,
            scenarios=scenarios,
            forecast_layer_comparisons=comparisons,
            section_status_summary=section_status_summary,
            policies=policies,
            grounded_summary=grounded_summary,
            traceability=traceability,
            versions=versions,
            warnings=warnings,
            limitations=limitations,
            evidence_replay=evidence_replay,
        )
        result.deterministic_hash = analysis_payload_hash(result)
        saved = self.result_repository.save(result)
        metrics.increment(
            f"analysis_{str(getattr(saved.status, 'value', saved.status)).lower()}_total"
        )
        self.research_pipeline.audit_repo.update_run(request.run_id, str(saved.status))
        return AnalysisExecution(saved, self._report_from_result(store, saved), core_research)

    @staticmethod
    def _report_from_result(store: StoreProfile, result: AnalysisResultV1) -> DeterministicReportPayload | None:
        baseline = result.scenarios.get("BASELINE")
        if not baseline:
            return None
        return render_deterministic_report(
            run_id=result.run_id,
            store_profile=store,
            as_of_date=result.as_of_date.isoformat(),
            baseline_scenario=baseline,
            low_impact_scenario=result.scenarios.get("LOW_IMPACT"),
            high_impact_scenario=result.scenarios.get("HIGH_IMPACT"),
            relief_options=result.policies.benefit_simulations,
        )
