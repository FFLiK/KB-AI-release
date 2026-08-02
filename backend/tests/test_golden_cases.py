# Phase 22.2 implementation note.
from decimal import Decimal
import pytest

from src.contracts.store import StoreProfile, MonthlyHistory, MonthlyCostDetail, MonthlyFixedCostDetail
from src.contracts.loan import Loan
from src.finance.loan import calculate_loan_schedule, quantize_krw
from src.finance.break_even import calculate_bep
from src.finance.cashflow import calculate_monthly_cashflow
from src.finance.scenario import run_financial_scenario
from src.relief.policy_schema import PolicySchema
from src.relief.benefit_simulator import simulate_policy_benefit

@pytest.fixture
def base_golden_store():
    """Phase 22.2 test."""
    return StoreProfile(
        store_id="STORE-GOLDEN-01",
        business_type_code="FNB_CAFE",
        address="서울특별시 강남구 테헤란로 123",
        minimum_operating_cash_krw=Decimal("5000000"),
        current_cash_krw=Decimal("10000000"),
        forecast_horizon_months=6,
        monthly_history=[
            MonthlyHistory(
                month="2026-07",
                revenue_krw=Decimal("30000000"),
                variable_costs=MonthlyCostDetail(
                    ingredients_krw=Decimal("9000000"),
                    platform_fee_krw=Decimal("3000000"),
                    payment_fee_krw=Decimal("600000"),
                ),
                fixed_costs=MonthlyFixedCostDetail(
                    rent_krw=Decimal("4000000"),
                    labor_krw=Decimal("7000000"),
                    utilities_krw=Decimal("1000000"),
                    other_krw=Decimal("500000"),
                ),
            )
        ],
        loans=[
            Loan(
                loan_id="LOAN-GOLDEN-01",
                principal_balance_krw=Decimal("50000000"),
                annual_interest_rate=Decimal("0.06"),  # Step 0.
                rate_type="VARIABLE",
                repayment_type="BULLET",  # Implementation note.
                remaining_months=12,
            )
        ],
    )

def test_golden_case_1_interest_rate_increase(base_golden_store):
    """Phase 22.2 test."""
    # Step 1.
    sch_base, _ = calculate_loan_schedule(base_golden_store.loans[0], forecast_horizon_months=1, rate_change_delta=Decimal("0"))
    assert quantize_krw(sch_base[0].interest_payment_krw) == Decimal("250000")

    # Step 2.
    sch_up, _ = calculate_loan_schedule(base_golden_store.loans[0], forecast_horizon_months=1, rate_change_delta=Decimal("0.01"))
    expected_interest = Decimal("50000000") * Decimal("0.07") / Decimal("12")

    assert abs(sch_up[0].interest_payment_krw - expected_interest) < Decimal("0.01")
    assert quantize_krw(sch_up[0].interest_payment_krw) == Decimal("291667")


def test_golden_case_2_revenue_drop_10_percent(base_golden_store):
    """Phase 22.2 test."""
    rev_base = Decimal("30000000")
    rev_drop = rev_base * Decimal("0.90")  # 27,000,000
    var_cost_drop = Decimal("12600000") * Decimal("0.90")  # 11,340,000
    fixed_cost = Decimal("12500000")

    bep = calculate_bep(
        month_index=1,
        revenue_forecast_krw=rev_drop,
        total_variable_cost_krw=var_cost_drop,
        operating_fixed_cost_krw=fixed_cost,
        interest_expense_krw=Decimal("250000"),
        principal_payment_krw=Decimal("0"),
    )

    assert bep.contribution_margin_ratio == Decimal("0.58")
    expected_op_bep = fixed_cost / Decimal("0.58")
    assert bep.operating_bep_krw == expected_op_bep


def test_golden_case_3_rent_increase(base_golden_store):
    """Phase 22.2 test."""
    res_base = run_financial_scenario(base_golden_store, scenario_name="BASELINE")

    # Implementation note.
    store_rent_up = base_golden_store.model_copy(deep=True)
    store_rent_up.monthly_history[0].fixed_costs.rent_krw += Decimal("500000")

    res_rent_up = run_financial_scenario(store_rent_up, scenario_name="RENT_UP")

    # Implementation note.
    base_cf1 = res_base.monthly_cash_flows[0].net_cash_flow_krw
    up_cf1 = res_rent_up.monthly_cash_flows[0].net_cash_flow_krw
    assert up_cf1 == base_cf1 - Decimal("500000")


def test_golden_case_4_interest_relief(base_golden_store):
    """Phase 22.2 test."""
    baseline_res = run_financial_scenario(base_golden_store, scenario_name="BASELINE")

    policy_discount = PolicySchema(
        policy_id="POL-GOLDEN-RELIEF",
        name="소상공인 2%p 금리우대",
        provider="KB국민은행",
        interest_rate_discount=Decimal("0.02"),
    )

    benefit = simulate_policy_benefit(base_golden_store, policy_discount, baseline_res)
    assert quantize_krw(benefit.cumulative_interest_savings_krw) == Decimal("500000")
