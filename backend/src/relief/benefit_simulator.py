# Phase 18.4 implementation note.
from decimal import Decimal
from typing import Dict, Any, List
from pydantic import BaseModel, Field

from src.contracts.research import StrictModel
from src.contracts.store import StoreProfile
from src.contracts.financial import FinancialScenarioResult
from src.relief.policy_schema import PolicySchema
from src.finance.scenario import run_financial_scenario

class ReliefBenefitComparison(StrictModel):
    policy_id: str
    policy_name: str
    eligibility_status: str
    original_cash_burn_date: str = "N/A"
    simulated_cash_burn_date: str = "N/A"
    runway_extension_days: int = 0
    cumulative_interest_savings_krw: Decimal = Decimal("0")

def simulate_policy_benefit(
    store_profile: StoreProfile,
    policy: PolicySchema,
    baseline_result: FinancialScenarioResult,
) -> ReliefBenefitComparison:
    """Phase 18.4 documentation."""
    # Implementation note.
    modified_loans = []
    for loan in store_profile.loans:
        loan_copy = loan.model_copy()
        # Implementation note.
        if policy.interest_rate_discount > Decimal("0"):
            new_rate = loan_copy.annual_interest_rate - policy.interest_rate_discount
            loan_copy.annual_interest_rate = max(Decimal("0"), new_rate)
        modified_loans.append(loan_copy)

    modified_store = store_profile.model_copy()
    modified_store.loans = modified_loans

    # Phase 18.4 implementation note.
    sim_result = run_financial_scenario(modified_store, scenario_name=f"RELIEF_{policy.policy_id}")

    # Implementation note.
    base_interest_total = sum(
        cf.interest_payment_krw for cf in baseline_result.monthly_cash_flows
    )
    sim_interest_total = sum(
        cf.interest_payment_krw for cf in sim_result.monthly_cash_flows
    )
    savings = base_interest_total - sim_interest_total

    orig_burn_date = baseline_result.cash_burn_result.cash_burn_date or "NONE"
    sim_burn_date = sim_result.cash_burn_result.cash_burn_date or "NONE"

    return ReliefBenefitComparison(
        policy_id=policy.policy_id,
        policy_name=policy.name,
        eligibility_status="ELIGIBLE_ON_DECLARED_RULES",
        original_cash_burn_date=orig_burn_date,
        simulated_cash_burn_date=sim_burn_date,
        cumulative_interest_savings_krw=savings,
    )
