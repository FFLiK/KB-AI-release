from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.contracts.loan import Loan
from src.contracts.official import OfficialDataRequest
from src.contracts.store import StoreProfile
from src.finance.loan import calculate_loan_schedule
from src.forecasting.baseline import NaiveBaselineModel
from src.ingestion.official_api.ecos import ECOSAdapter
from src.orchestration.pipeline import run_analysis


def test_malformed_official_observation_is_not_replaced_with_zero_or_fixed_date():
    adapter = ECOSAdapter()
    assert adapter.normalize([{"TIME": "bad", "DATA_VALUE": "3.5"}]) == []
    assert adapter.normalize([{"TIME": "202607"}]) == []


def test_legacy_baseline_and_pipeline_fail_closed_without_history():
    with pytest.raises(ValueError, match="INSUFFICIENT_DATA"):
        NaiveBaselineModel().predict_revenue([], 3)
    profile = StoreProfile(
        store_id="NO-HISTORY", address="Seoul",
        minimum_operating_cash_krw=Decimal("0"), current_cash_krw=Decimal("100"),
    )
    report, state = run_analysis(profile)
    assert report.baseline_scenario.monthly_cash_flows == []
    assert state.financial_results["BASELINE"]["metadata"]["status"] == "INSUFFICIENT_DATA"


def test_policy_principal_grace_changes_repayment_schedule():
    loan = Loan(
        loan_id="LOAN-GRACE", principal_balance_krw=Decimal("1200"),
        annual_interest_rate=Decimal("0.12"), repayment_type="EQUAL_PRINCIPAL",
        remaining_months=12,
    )
    normal, _ = calculate_loan_schedule(loan, 3)
    grace, metadata = calculate_loan_schedule(loan, 3, principal_grace_months=2)
    assert normal[0].principal_payment_krw > 0
    assert grace[0].principal_payment_krw == grace[1].principal_payment_krw == 0
    assert grace[2].principal_payment_krw > 0
    assert metadata["principal_grace_months"] == "2"


def test_new_public_contracts_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        OfficialDataRequest(provider="ECOS", indicator_id="BASE_RATE", unexpected=True)
