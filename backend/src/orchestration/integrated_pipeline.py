"""Backward-compatible facade over the single AnalysisOrchestrator."""
from __future__ import annotations

from dataclasses import dataclass

from src.contracts.financial import FinancialScenarioResult
from src.contracts.research import ResearchRequest
from src.contracts.store import StoreProfile
from src.contracts.store_signal import ScenarioAdjustment, StoreSignal
from src.forecasting.pipeline import BaselineForecastPipeline
from src.orchestration.analysis_orchestrator import AnalysisOrchestrator
from src.orchestration.official_data_pipeline import OfficialDataPipeline
from src.orchestration.research_pipeline import ResearchPipeline, ResearchPipelineResult
from src.orchestration.state import AppState
from src.reporting.deterministic_report import DeterministicReportPayload
from src.storage.analysis_repository import (
    AnalysisResultRepository,
    ForecastRepository,
    OfficialDataRepository,
    ScenarioResultRepository,
)


@dataclass
class IntegratedAnalysisResult:
    report: DeterministicReportPayload
    app_state: AppState
    research: ResearchPipelineResult
    signals: list[StoreSignal]
    adjustments: dict[str, ScenarioAdjustment]
    financial_results: dict[str, FinancialScenarioResult]


def run_integrated_analysis(
    store: StoreProfile,
    request: ResearchRequest,
    research_pipeline: ResearchPipeline,
) -> IntegratedAnalysisResult:
    db = research_pipeline.audit_repo.db
    orchestrator = AnalysisOrchestrator(
        research_pipeline=research_pipeline,
        official_pipeline=OfficialDataPipeline(repository=OfficialDataRepository(db)),
        forecast_pipeline=BaselineForecastPipeline(ForecastRepository(db)),
        result_repository=AnalysisResultRepository(db),
        scenario_repository=ScenarioResultRepository(db),
    )
    execution = orchestrator.run(store, request)
    result = execution.result
    if execution.report is None:
        raise ValueError("Analysis did not produce a financial report")
    legacy_adjustments = {}
    for name, adjustment in result.adjustments.items():
        if adjustment.months:
            rev_mult = sum(m.revenue_multiplier for m in adjustment.months) / len(adjustment.months)
            var_mult = sum(m.variable_cost_multiplier for m in adjustment.months) / len(adjustment.months)
            fix_mult = sum(m.fixed_cost_multiplier for m in adjustment.months) / len(adjustment.months)
            rate_delta = sum(m.interest_rate_delta for m in adjustment.months) / len(adjustment.months)
        else:
            rev_mult, var_mult, fix_mult, rate_delta = 1, 1, 1, 0

        legacy_adjustments[name] = ScenarioAdjustment(
            scenario=name,
            revenue_multiplier=rev_mult,
            variable_cost_multiplier=var_mult,
            fixed_cost_multiplier=fix_mult,
            interest_rate_delta=rate_delta,
            signal_ids=sorted({item for value in adjustment.months for item in value.signal_ids}),
            event_ids=sorted({item for value in adjustment.months for item in value.event_ids}),
            source_ids=adjustment.source_ids,
            coefficient_version=adjustment.coefficient_version,
        )
    app_state = AppState(
        run_id=result.run_id,
        as_of_date=result.as_of_date.isoformat(),
        input_profile=store.model_dump(mode="json"),
        official_data_bundle=result.official_data.model_dump(mode="json"),
        official_data_vintages=[item.model_dump(mode="json") for item in result.official_data.source_vintages],
        baseline_model_results=result.baseline.model_dump(mode="json"),
        model_metrics=[item.model_dump(mode="json") for item in result.baseline.candidate_metrics],
        accepted_events=[item.model_dump(mode="json") for item in result.research.accepted_events],
        rejected_events=[item.model_dump(mode="json") for item in result.research.rejected_events],
        signal_scores={item.signal_id: item.model_dump(mode="json") for item in result.signals},
        scenario_adjustments={key: value.model_dump(mode="json") for key, value in result.adjustments.items()},
        financial_results={key: value.model_dump(mode="json") for key, value in result.scenarios.items()},
        policy_candidates=[item.model_dump(mode="json") for item in result.policies.candidates],
        policy_validation_logs=result.policies.validation_results,
        eligibility_results=[item.model_dump(mode="json") for item in result.policies.eligibility_results],
        benefit_simulations=[item.model_dump(mode="json") for item in result.policies.benefit_simulations],
        section_statuses={str(key): value.model_dump(mode="json") for key, value in result.sections.items()},
        version_manifest=result.versions.model_dump(mode="json"),
        deterministic_result_hash=result.deterministic_hash,
        result_id=result.result_id,
        result_version=result.result_version,
        deterministic_report=execution.report.model_dump(mode="json"),
    )
    return IntegratedAnalysisResult(
        report=execution.report,
        app_state=app_state,
        research=execution.research,
        signals=result.signals,
        adjustments=legacy_adjustments,
        financial_results=result.scenarios,
    )
