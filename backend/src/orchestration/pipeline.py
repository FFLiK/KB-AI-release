"""Legacy deterministic-only entry point.

New HTTP and research integrations use AnalysisOrchestrator. This wrapper keeps
the original function signature while failing closed when history is absent.
"""
import os
import uuid
from decimal import Decimal
from typing import List, Tuple

from src.contracts.financial import CashBurnResult, FinancialScenarioResult
from src.config.credential_validation import credential_status
from src.contracts.store import StoreProfile
from src.finance.scenario import run_financial_scenario
from src.orchestration.state import AppState
from src.relief.benefit_simulator import simulate_policy_benefit
from src.relief.eligibility_rules import evaluate_policy_eligibility
from src.relief.policy_schema import PolicySchema
from src.reporting.deterministic_report import DeterministicReportPayload, render_deterministic_report


def _load_env_file(env_path: str = ".env") -> None:
    if os.getenv("KB_AI_SKIP_DOTENV") == "1":
        return
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("'").strip('"')
                    if key and credential_status(value) != "PLACEHOLDER" and not os.environ.get(key):
                        os.environ[key] = value
        except Exception:
            pass


_load_env_file()


def _insufficient_scenario(name: str) -> FinancialScenarioResult:
    return FinancialScenarioResult(
        scenario_name=name,
        monthly_cash_flows=[],
        bep_results=[],
        cash_burn_result=CashBurnResult(
            horizon_status="NO_BURN_WITHIN_HORIZON",
            calculation_assumption="NOT_CALCULATED_INSUFFICIENT_DATA",
        ),
        metadata={
            "status": "INSUFFICIENT_DATA",
            "failure_reason": "Revenue and cost history are required",
            "calculation_version": "legacy_fail_closed.v1",
        },
    )


def run_analysis(
    store_profile: StoreProfile,
    as_of_date: str = "2026-08-01",
    available_policies: List[PolicySchema] | None = None,
) -> Tuple[DeterministicReportPayload, AppState]:
    _load_env_file()
    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
    app_state = AppState(
        run_id=run_id,
        as_of_date=as_of_date,
        input_profile=store_profile.model_dump(mode="json"),
    )

    if store_profile.monthly_history:
        baseline = run_financial_scenario(store_profile, scenario_name="BASELINE")
        low_impact = run_financial_scenario(
            store_profile, scenario_name="LOW_IMPACT", revenue_multiplier=Decimal("0.95")
        )
        high_impact = run_financial_scenario(
            store_profile, scenario_name="HIGH_IMPACT", revenue_multiplier=Decimal("0.90"),
            interest_rate_delta=Decimal("0.01"),
        )
    else:
        baseline = _insufficient_scenario("BASELINE")
        low_impact = _insufficient_scenario("LOW_IMPACT")
        high_impact = _insufficient_scenario("HIGH_IMPACT")

    app_state.financial_results = {
        "BASELINE": baseline.model_dump(mode="json"),
        "LOW_IMPACT": low_impact.model_dump(mode="json"),
        "HIGH_IMPACT": high_impact.model_dump(mode="json"),
    }
    relief_benefits = []
    if available_policies and store_profile.monthly_history:
        for policy in available_policies:
            status, _ = evaluate_policy_eligibility(store_profile, policy)
            if status == "ELIGIBLE_ON_DECLARED_RULES":
                relief_benefits.append(simulate_policy_benefit(store_profile, policy, baseline))
    app_state.benefit_simulations = [item.model_dump(mode="json") for item in relief_benefits]
    report = render_deterministic_report(
        run_id=run_id,
        store_profile=store_profile,
        as_of_date=as_of_date,
        baseline_scenario=baseline,
        low_impact_scenario=low_impact,
        high_impact_scenario=high_impact,
        relief_options=relief_benefits,
    )
    app_state.deterministic_report = report.model_dump(mode="json")
    return report, app_state
