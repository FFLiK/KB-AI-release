# Phase 5.2 implementation note.
from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from src.contracts.research import StrictModel
class CustomPaymentSchedule(StrictModel):
    """Phase 5.2 documentation."""
    month: str = Field(description="상환 월 (YYYY-MM 또는 t1, t2 등 회차 식별자)")
    principal_payment_krw: Decimal = Field(ge=Decimal("0"), description="회차별 원금 상환액")
    interest_payment_krw: Decimal = Field(ge=Decimal("0"), description="회차별 이자 상환액")

class Loan(StrictModel):
    """Phase 5.2 documentation."""
    loan_id: str
    principal_balance_krw: Decimal = Field(ge=Decimal("0"), description="대출 잔액 (KRW)")
    annual_interest_rate: Decimal = Field(ge=Decimal("0"), description="연 이자율 (비율 또는 소수점, 예: 0.065 = 6.5%)")
    rate_type: Literal["FIXED", "VARIABLE"] = Field(default="FIXED", description="금리 유형")
    rate_reference: Optional[str] = Field(default=None, description="기준 금리 명칭 (예: COFIX)")
    spread: Decimal = Field(default=Decimal("0"), description="가산 금리 (비율)")
    repayment_type: Literal["BULLET", "EQUAL_PRINCIPAL", "AMORTIZING", "CUSTOM_SCHEDULE"] = Field(
        description="상환 방식: BULLET(만기일시), EQUAL_PRINCIPAL(원금균등), AMORTIZING(원리금균등), CUSTOM_SCHEDULE(별도 스케줄)"
    )
    remaining_months: int = Field(gt=0, description="잔여 상환 개월 수")
    next_payment_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])$", description="다음 납입일 (YYYY-MM-DD)")
    grace_end_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])$", description="거치기간 종료일 (YYYY-MM-DD)")
    renewal_month: Optional[int] = Field(default=None, ge=1, description="변동금리 갱신 시점 (1-based relative month index t, 미입력 시 즉시 적용)")
    custom_schedule: Optional[List[CustomPaymentSchedule]] = Field(
        default=None, description="CUSTOM_SCHEDULE 상환 방식인 경우 필수 제공되는 회차별 스케줄 리스트"
    )
