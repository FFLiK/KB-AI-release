# Unit Tests for Step 1: Deterministic Finance Engine
from decimal import Decimal
import pytest
from pydantic import ValidationError

from src.contracts.store import StoreProfile, MonthlyHistory, MonthlyCostDetail, MonthlyFixedCostDetail, CostExposures
from src.contracts.loan import Loan, CustomPaymentSchedule
from src.finance.loan import calculate_loan_schedule
from src.finance.break_even import calculate_bep
from src.finance.cashflow import calculate_monthly_cashflow, evaluate_cash_burn_and_liquidity_risk
from src.finance.scenario import run_financial_scenario


def test_bullet_loan_schedule():
    """Phase 15.1 test."""
    loan = Loan(
        loan_id="LOAN-BULLET",
        principal_balance_krw=Decimal("12000000"),
        annual_interest_rate=Decimal("0.12"),  # Implementation note.
        rate_type="FIXED",
        repayment_type="BULLET",
        remaining_months=6,
    )
    schedule, meta = calculate_loan_schedule(loan, forecast_horizon_months=6)

    assert len(schedule) == 6
    # Step 0.
    for t in range(1, 6):
        assert schedule[t-1].principal_payment_krw == Decimal("0")
        assert schedule[t-1].interest_payment_krw == Decimal("120000")
        assert schedule[t-1].closing_balance_krw == Decimal("12000000")

    # Implementation note.
    assert schedule[5].principal_payment_krw == Decimal("12000000")
    assert schedule[5].closing_balance_krw == Decimal("0")


def test_equal_principal_loan_schedule():
    """Phase 15.2 test."""
    loan = Loan(
        loan_id="LOAN-EQ-PRIN",
        principal_balance_krw=Decimal("6000000"),
        annual_interest_rate=Decimal("0.12"),  # Implementation note.
        rate_type="FIXED",
        repayment_type="EQUAL_PRINCIPAL",
        remaining_months=6,
    )
    schedule, meta = calculate_loan_schedule(loan, forecast_horizon_months=6)

    assert len(schedule) == 6
    # Implementation note.
    for t in range(1, 7):
        assert schedule[t-1].principal_payment_krw == Decimal("1000000")

    # Step 0.
    assert schedule[0].interest_payment_krw == Decimal("60000")
    # Step 0.
    assert schedule[5].interest_payment_krw == Decimal("10000")
    assert schedule[5].closing_balance_krw == Decimal("0")


def test_amortizing_loan_schedule_zero_rate():
    """Phase 15.3 test."""
    loan = Loan(
        loan_id="LOAN-ZERO-RATE",
        principal_balance_krw=Decimal("6000000"),
        annual_interest_rate=Decimal("0"),
        rate_type="FIXED",
        repayment_type="AMORTIZING",
        remaining_months=6,
    )
    schedule, meta = calculate_loan_schedule(loan, forecast_horizon_months=6)

    assert len(schedule) == 6
    for t in range(1, 7):
        assert schedule[t-1].interest_payment_krw == Decimal("0")
        assert schedule[t-1].principal_payment_krw == Decimal("1000000")
    assert schedule[5].closing_balance_krw == Decimal("0")


def test_custom_schedule_and_fail_closed():
    """Test."""
    custom_list = [
        CustomPaymentSchedule(month="2026-08", principal_payment_krw=Decimal("500000"), interest_payment_krw=Decimal("50000")),
        CustomPaymentSchedule(month="2026-09", principal_payment_krw=Decimal("500000"), interest_payment_krw=Decimal("45000")),
    ]
    loan_valid = Loan(
        loan_id="LOAN-CUSTOM-OK",
        principal_balance_krw=Decimal("1000000"),
        annual_interest_rate=Decimal("0.05"),
        repayment_type="CUSTOM_SCHEDULE",
        remaining_months=2,
        custom_schedule=custom_list,
    )
    sch, _ = calculate_loan_schedule(loan_valid, forecast_horizon_months=2)
    assert sch[0].principal_payment_krw == Decimal("500000")
    assert sch[0].interest_payment_krw == Decimal("50000")

    # Implementation note.
    loan_invalid = Loan(
        loan_id="LOAN-CUSTOM-FAIL",
        principal_balance_krw=Decimal("1500000"),
        annual_interest_rate=Decimal("0.05"),
        repayment_type="CUSTOM_SCHEDULE",
        remaining_months=3,
        custom_schedule=custom_list,
    )
    with pytest.raises(ValueError, match="Fail-Closed"):
        calculate_loan_schedule(loan_invalid, forecast_horizon_months=3)


def test_variable_rate_renewal_scheduling():
    """Test."""
    loan = Loan(
        loan_id="LOAN-VAR",
        principal_balance_krw=Decimal("10000000"),
        annual_interest_rate=Decimal("0.06"),  # Implementation note.
        rate_type="VARIABLE",
        repayment_type="BULLET",
        remaining_months=6,
        renewal_month=3,  # Implementation note.
    )
    # Step 0.
    schedule, meta = calculate_loan_schedule(loan, forecast_horizon_months=4, rate_change_delta=Decimal("0.02"))

    # Implementation note.
    assert schedule[0].applied_annual_rate == Decimal("0.06")
    assert schedule[1].applied_annual_rate == Decimal("0.06")

    # Step 0.
    assert schedule[2].applied_annual_rate == Decimal("0.08")
    assert schedule[3].applied_annual_rate == Decimal("0.08")


def test_bep_calculation_normal_and_unattainable():
    """Phase 16.1 test."""
    # Step 1.
    bep_norm = calculate_bep(
        month_index=1,
        revenue_forecast_krw=Decimal("30000000"),
        total_variable_cost_krw=Decimal("15000000"),
        operating_fixed_cost_krw=Decimal("10000000"),
        interest_expense_krw=Decimal("1000000"),
        principal_payment_krw=Decimal("2000000"),
    )
    assert bep_norm.bep_status == "NORMAL"
    assert bep_norm.contribution_margin_ratio == Decimal("0.5")
    assert bep_norm.operating_bep_krw == Decimal("20000000")  # 10m / 0.5
    assert bep_norm.financial_bep_krw == Decimal("22000000")  # 11m / 0.5
    assert bep_norm.cash_bep_krw == Decimal("26000000")       # (10m+1m+2m) / 0.5

    # Step 2.
    bep_fail = calculate_bep(
        month_index=1,
        revenue_forecast_krw=Decimal("30000000"),
        total_variable_cost_krw=Decimal("30000000"),
        operating_fixed_cost_krw=Decimal("10000000"),
        interest_expense_krw=Decimal("1000000"),
        principal_payment_krw=Decimal("2000000"),
    )
    assert bep_fail.bep_status == "UNATTAINABLE"
    assert bep_fail.bep_failure_reason == "CONTRIBUTION_MARGIN_RATIO_NON_POSITIVE"
    assert bep_fail.operating_bep_krw is None
    assert bep_fail.financial_bep_krw is None
    assert bep_fail.cash_bep_krw is None


def test_cashflow_and_cash_burn():
    """Phase 16.3 test."""
    # Step 1.
    # Implementation note.
    # Step 15.
    cf1 = calculate_monthly_cashflow(
        month_index=1,
        month_str="2026-08",
        beginning_cash_krw=Decimal("10000000"),
        revenue_cash_krw=Decimal("20000000"),
        variable_costs_cash_krw=Decimal("15000000"),
        fixed_costs_cash_krw=Decimal("15000000"),
        interest_payment_krw=Decimal("5000000"),
        principal_payment_krw=Decimal("5000000"),
    )
    assert cf1.net_cash_flow_krw == Decimal("-20000000")
    assert cf1.ending_cash_krw == Decimal("-10000000")

    burn_res = evaluate_cash_burn_and_liquidity_risk(
        monthly_cash_flows=[cf1],
        minimum_operating_cash_krw=Decimal("5000000"),
    )
    assert burn_res.horizon_status == "BURN_WITHIN_HORIZON"
    assert burn_res.calculation_assumption == "MONTHLY_EVEN_DISTRIBUTION"
    assert burn_res.cash_burn_date == "2026-08-15"
    assert burn_res.liquidity_risk_date == "2026-08-01"

    # Step 2.
    cf_pos = calculate_monthly_cashflow(
        month_index=1,
        month_str="2026-08",
        beginning_cash_krw=Decimal("10000000"),
        revenue_cash_krw=Decimal("30000000"),
        variable_costs_cash_krw=Decimal("10000000"),
        fixed_costs_cash_krw=Decimal("10000000"),
        interest_payment_krw=Decimal("1000000"),
        principal_payment_krw=Decimal("1000000"),
    )
    assert cf_pos.ending_cash_krw == Decimal("18000000")

    burn_res_pos = evaluate_cash_burn_and_liquidity_risk(
        monthly_cash_flows=[cf_pos],
        minimum_operating_cash_krw=Decimal("5000000"),
    )
    assert burn_res_pos.cash_burn_date is None
    assert burn_res_pos.horizon_status == "NO_BURN_WITHIN_HORIZON"
    assert burn_res_pos.liquidity_risk_date is None


def test_financial_scenario_execution():
    """Phase 17 test."""
    store = StoreProfile(
        store_id="STORE-TEST-01",
        address="서울특별시 강남구 테헤란로 123",
        minimum_operating_cash_krw=Decimal("5000000"),
        current_cash_krw=Decimal("15000000"),
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
                loan_id="LOAN-01",
                principal_balance_krw=Decimal("20000000"),
                annual_interest_rate=Decimal("0.05"),
                repayment_type="EQUAL_PRINCIPAL",
                remaining_months=12,
            )
        ],
    )

    result = run_financial_scenario(store, scenario_name="BASELINE")
    assert result.scenario_name == "BASELINE"
    assert len(result.monthly_cash_flows) == 6
    assert len(result.bep_results) == 6
    assert result.cash_burn_result.calculation_assumption == "MONTHLY_EVEN_DISTRIBUTION"
