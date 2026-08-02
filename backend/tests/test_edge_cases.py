# Destructive Edge-Cases & Stress Test Suite (6-Domain Deep Verification)
from decimal import Decimal
import pytest

from src.contracts.store import StoreProfile, MonthlyHistory, MonthlyCostDetail, MonthlyFixedCostDetail
from src.contracts.loan import Loan
from src.finance.loan import calculate_loan_schedule, _decimal_pow, quantize_krw
from src.finance.cashflow import calculate_monthly_cashflow, evaluate_cash_burn_and_liquidity_risk
from src.ingestion.official_api.ecos import ECOSAdapter
from src.reporting.chatbot_tools import DeterministicChatbotToolHandler
from src.orchestration.pipeline import run_analysis

def test_pure_decimal_precision_no_float_drift():
    """Test."""
    loan = Loan(
        loan_id="L-DEC-PURE",
        principal_balance_krw=Decimal("100000000"),  # Implementation note.
        annual_interest_rate=Decimal("0.055"),       # Step 5.
        repayment_type="AMORTIZING",
        remaining_months=120,                        # Implementation note.
    )
    schedule, _ = calculate_loan_schedule(loan, forecast_horizon_months=120)

    assert len(schedule) == 120
    # Implementation note.
    assert schedule[-1].closing_balance_krw == Decimal("0")
    # Implementation note.
    assert isinstance(schedule[0].interest_payment_krw, Decimal)
    assert isinstance(schedule[0].principal_payment_krw, Decimal)


def test_leap_year_february_29_cash_burn():
    """Test."""
    # Implementation note.
    # Implementation note.
    cf = calculate_monthly_cashflow(
        month_index=1,
        month_str="2028-02",
        beginning_cash_krw=Decimal("14500000"),
        revenue_cash_krw=Decimal("10000000"),
        variable_costs_cash_krw=Decimal("15000000"),
        fixed_costs_cash_krw=Decimal("24000000"),
        interest_payment_krw=Decimal("4500000"),
        principal_payment_krw=Decimal("0"),
    )
    assert cf.net_cash_flow_krw == Decimal("-33500000")

    res = evaluate_cash_burn_and_liquidity_risk([cf], minimum_operating_cash_krw=Decimal("5000000"))
    assert res.cash_burn_date is not None
    assert res.cash_burn_date == "2028-02-12"
    assert res.horizon_status == "BURN_WITHIN_HORIZON"


def test_zero_cash_at_start_boundary():
    """Test."""
    cf_zero = calculate_monthly_cashflow(
        month_index=1,
        month_str="2026-08",
        beginning_cash_krw=Decimal("0"),
        revenue_cash_krw=Decimal("10000000"),
        variable_costs_cash_krw=Decimal("15000000"),
        fixed_costs_cash_krw=Decimal("5000000"),
        interest_payment_krw=Decimal("1000000"),
        principal_payment_krw=Decimal("0"),
    )
    res = evaluate_cash_burn_and_liquidity_risk([cf_zero], minimum_operating_cash_krw=Decimal("1000000"))
    assert res.cash_burn_date == "2026-08-01"


def test_api_adapter_defensive_fallback():
    """Test."""
    adapter = ECOSAdapter()
    parsed_bad = adapter.parse(None)
    assert parsed_bad is None or parsed_bad == []

    obs = adapter.process({"indicator_id": "INVALID"})
    assert isinstance(obs, list)


def test_chatbot_tools_malformed_arguments():
    """Test."""
    handler = DeterministicChatbotToolHandler(current_report_payload=None)

    # Step 1.
    res1 = handler.get_result(result_id=None)
    assert res1["status"] == "ERROR"

    # Step 2.
    res2 = handler.run_what_if(store_profile=None, revenue_delta=-0.1)
    assert res2["status"] == "ERROR"

    # Step 3.
    res3 = handler.compare_relief_options(relief_options="MALFORMED_STRING")
    assert res3 == []


def test_concurrency_state_isolation():
    """Test."""
    store_a = StoreProfile(
        store_id="STORE-A",
        address="서울",
        minimum_operating_cash_krw=Decimal("1000000"),
        current_cash_krw=Decimal("5000000"),
    )
    store_b = StoreProfile(
        store_id="STORE-B",
        address="부산",
        minimum_operating_cash_krw=Decimal("9000000"),
        current_cash_krw=Decimal("90000000"),
    )

    payload_a, state_a = run_analysis(store_a)
    payload_b, state_b = run_analysis(store_b)

    assert state_a.run_id != state_b.run_id
    assert payload_a.store_id == "STORE-A"
    assert payload_b.store_id == "STORE-B"
    assert payload_a.current_cash_krw == Decimal("5000000")
    assert payload_b.current_cash_krw == Decimal("90000000")
