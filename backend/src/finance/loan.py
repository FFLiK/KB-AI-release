"""Deterministic Decimal loan repayment schedules."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple

from src.contracts.financial import MonthlyLoanPayment
from src.contracts.loan import Loan


def quantize_krw(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _decimal_pow(base: Decimal, exponent: int) -> Decimal:
    result = Decimal("1")
    for _ in range(exponent):
        result *= base
    return result


def _month_key(start: date, offset: int) -> str:
    index = start.year * 12 + start.month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _zero_payment(loan: Loan, month_index: int, balance: Decimal, rate: Decimal) -> MonthlyLoanPayment:
    return MonthlyLoanPayment(
        loan_id=loan.loan_id,
        month_index=month_index,
        opening_balance_krw=balance,
        interest_payment_krw=Decimal("0"),
        principal_payment_krw=Decimal("0"),
        closing_balance_krw=balance,
        applied_annual_rate=rate,
    )


def calculate_loan_schedule(
    loan: Loan,
    forecast_horizon_months: int,
    rate_change_delta: Decimal = Decimal("0"),
    principal_grace_months: int = 0,
    forecast_start: date | None = None,
) -> Tuple[List[MonthlyLoanPayment], Dict[str, str]]:
    metadata: Dict[str, str] = {
        "rate_reference": loan.rate_reference or "NONE",
        "spread": str(loan.spread),
        "schedule_basis": "MONTHLY_CONTRACT_DATES" if forecast_start else "RELATIVE_MONTH_INDEX",
    }
    schedule: List[MonthlyLoanPayment] = []
    opening_balance = loan.principal_balance_krw
    initial_principal = loan.principal_balance_krw
    remaining_months = loan.remaining_months
    is_variable = loan.rate_type == "VARIABLE"
    renewal_month = loan.renewal_month
    if is_variable and renewal_month is None:
        metadata["rate_renewal_applied"] = "IMMEDIATE_AT_START"
        renewal_month = 1

    next_payment_month = loan.next_payment_date[:7] if loan.next_payment_date else None
    grace_end_month = loan.grace_end_date[:7] if loan.grace_end_date else None
    active_period = 0
    for month_index in range(1, forecast_horizon_months + 1):
        current_month = _month_key(forecast_start, month_index - 1) if forecast_start else None
        rate_applies = is_variable and month_index >= (renewal_month or 1)
        applied_rate = max(Decimal("0"), loan.annual_interest_rate + (rate_change_delta if rate_applies else 0))

        if opening_balance <= 0:
            schedule.append(_zero_payment(loan, month_index, Decimal("0"), applied_rate))
            continue
        if current_month and next_payment_month and current_month < next_payment_month:
            metadata["next_payment_date_applied"] = loan.next_payment_date or ""
            schedule.append(_zero_payment(loan, month_index, opening_balance, applied_rate))
            continue

        active_period += 1
        if active_period > remaining_months:
            schedule.append(_zero_payment(loan, month_index, opening_balance, applied_rate))
            continue
        monthly_rate = applied_rate / Decimal("12")
        principal_payment = Decimal("0")
        interest_payment = opening_balance * monthly_rate

        if loan.repayment_type == "BULLET":
            if active_period == remaining_months:
                principal_payment = opening_balance
        elif loan.repayment_type == "EQUAL_PRINCIPAL":
            principal_payment = min(opening_balance, initial_principal / Decimal(remaining_months))
        elif loan.repayment_type == "AMORTIZING":
            periods_left = remaining_months - active_period + 1
            if monthly_rate == 0:
                principal_payment = opening_balance / Decimal(periods_left)
                interest_payment = Decimal("0")
            else:
                factor = _decimal_pow(Decimal("1") + monthly_rate, periods_left)
                payment = opening_balance * monthly_rate * factor / (factor - Decimal("1"))
                principal_payment = min(opening_balance, payment - interest_payment)
            if active_period == remaining_months:
                principal_payment = opening_balance
        elif loan.repayment_type == "CUSTOM_SCHEDULE":
            if not loan.custom_schedule or len(loan.custom_schedule) < active_period:
                raise ValueError(
                    f"Fail-Closed: CUSTOM_SCHEDULE data missing for payment index {active_period} in loan '{loan.loan_id}'"
                )
            custom = loan.custom_schedule[active_period - 1]
            principal_payment = custom.principal_payment_krw
            interest_payment = custom.interest_payment_krw
        else:
            raise ValueError(f"Unsupported repayment_type: {loan.repayment_type}")

        contractual_grace = bool(current_month and grace_end_month and current_month <= grace_end_month)
        if active_period <= principal_grace_months or contractual_grace:
            principal_payment = Decimal("0")
            metadata["principal_grace_months"] = str(principal_grace_months)
            if contractual_grace:
                metadata["grace_end_date_applied"] = loan.grace_end_date or ""
        principal_payment = min(principal_payment, opening_balance)
        closing_balance = max(Decimal("0"), opening_balance - principal_payment)
        schedule.append(MonthlyLoanPayment(
            loan_id=loan.loan_id,
            month_index=month_index,
            opening_balance_krw=opening_balance,
            interest_payment_krw=interest_payment,
            principal_payment_krw=principal_payment,
            closing_balance_krw=closing_balance,
            applied_annual_rate=applied_rate,
        ))
        opening_balance = closing_balance
    return schedule, metadata
