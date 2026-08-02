# Unit Tests for Step 5: Relief Eligibility & Benefit Simulator Engine
from decimal import Decimal
import pytest

from src.contracts.store import StoreProfile, MonthlyHistory, MonthlyCostDetail, MonthlyFixedCostDetail
from src.contracts.loan import Loan
from src.relief.policy_schema import PolicySchema
from src.relief.eligibility_rules import evaluate_policy_eligibility
from src.relief.benefit_simulator import simulate_policy_benefit
from src.finance.scenario import run_financial_scenario

def test_eligibility_rules():
    """Phase 18.3 test."""
    store = StoreProfile(
        store_id="S-01",
        business_type_code="FNB_CAFE",
        address="서울",
        minimum_operating_cash_krw=Decimal("5000000"),
        current_cash_krw=Decimal("10000000"),
    )

    # Step 1.
    pol_ok = PolicySchema(
        policy_id="POL-01",
        name="소상공인 금리 우대",
        provider="KB",
        region_codes=["11"],
        industry_inclusions=["FNB_CAFE"],
    )
    status_ok, reason_ok = evaluate_policy_eligibility(store, pol_ok, store_region_code="11")
    assert status_ok == "ELIGIBLE_ON_DECLARED_RULES"

    # Step 2.
    status_region, _ = evaluate_policy_eligibility(store, pol_ok, store_region_code="26") # Implementation note.
    assert status_region == "INELIGIBLE"

    # Step 3.
    pol_closed = PolicySchema(
        policy_id="POL-02",
        name="종료된 정책",
        provider="KB",
        budget_status="CLOSED",
    )
    status_closed, _ = evaluate_policy_eligibility(store, pol_closed)
    assert status_closed == "CLOSED"


def test_benefit_simulator():
    """Phase 18.4 test."""
    store = StoreProfile(
        store_id="S-RELIEF-01",
        business_type_code="FNB",
        address="서울",
        minimum_operating_cash_krw=Decimal("5000000"),
        current_cash_krw=Decimal("10000000"),
        forecast_horizon_months=6,
        monthly_history=[
            MonthlyHistory(
                month="2026-07",
                revenue_krw=Decimal("30000000"),
                variable_costs=MonthlyCostDetail(ingredients_krw=Decimal("9000000")),
                fixed_costs=MonthlyFixedCostDetail(rent_krw=Decimal("4000000"), labor_krw=Decimal("6000000")),
            )
        ],
        loans=[
            Loan(
                loan_id="L-01",
                principal_balance_krw=Decimal("50000000"),
                annual_interest_rate=Decimal("0.08"),  # Implementation note.
                repayment_type="BULLET",
                remaining_months=6,
            )
        ]
    )

    baseline_res = run_financial_scenario(store, scenario_name="BASELINE")

    # Implementation note.
    policy = PolicySchema(
        policy_id="POL-DISCOUNT",
        name="금리 감면 정책",
        provider="소진공",
        interest_rate_discount=Decimal("0.02"),
    )

    comp = simulate_policy_benefit(store, policy, baseline_res)
    assert comp.cumulative_interest_savings_krw > Decimal("0")
