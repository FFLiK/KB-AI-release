"""Deterministic grounded summary generation and validation."""
from __future__ import annotations

from src.contracts.analysis import TraceabilityManifest
from src.contracts.financial import FinancialScenarioResult
from src.contracts.forecast import BaselineForecastBundle
from src.contracts.summary import GroundedStatement, GroundedSummary


def build_grounded_summary(
    result_id: str,
    baseline: BaselineForecastBundle,
    scenarios: dict[str, FinancialScenarioResult],
    traceability: TraceabilityManifest,
) -> GroundedSummary:
    statements: list[GroundedStatement] = []
    if baseline.monthly_forecasts:
        first = baseline.monthly_forecasts[0]
        statements.append(GroundedStatement(
            statement_id="SUMMARY-FORECAST-1",
            text=f"{first.month} baseline revenue forecast is {first.point} KRW.",
            citation_ids=[baseline.forecast_id],
            facts={"month": first.month, "revenue_forecast_krw": first.point},
        ))
    baseline_scenario = scenarios.get("BASELINE")
    if baseline_scenario and baseline_scenario.monthly_cash_flows:
        last = baseline_scenario.monthly_cash_flows[-1]
        scenario_id = baseline_scenario.metadata.get("scenario_id", "BASELINE")
        statements.append(GroundedStatement(
            statement_id="SUMMARY-CASH-1",
            text=f"Projected ending cash for {last.month_str} is {last.ending_cash_krw} KRW.",
            citation_ids=[scenario_id],
            facts={"month": last.month_str, "ending_cash_krw": last.ending_cash_krw},
        ))
    allowed = {
        *traceability.source_ids,
        *traceability.source_revision_ids,
        *traceability.official_snapshot_ids,
        *traceability.event_ids,
        *traceability.signal_ids,
        *traceability.policy_ids,
        *traceability.model_run_ids,
        *traceability.scenario_ids,
        *traceability.calculation_result_ids,
    }
    errors = [
        f"{statement.statement_id}: unknown citation {citation_id}"
        for statement in statements
        for citation_id in statement.citation_ids
        if citation_id not in allowed
    ]
    return GroundedSummary(
        summary_id=f"GS-{result_id}",
        result_id=result_id,
        statements=statements,
        validation_status="VALIDATED" if not errors else "FAILED",
        validation_errors=errors,
    )

