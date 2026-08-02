# src/contracts package initialization
from src.contracts.store import StoreProfile, MonthlyHistory, MonthlyCostDetail, MonthlyFixedCostDetail, CostExposures
from src.contracts.loan import Loan, CustomPaymentSchedule
from src.contracts.financial import (
    MonthlyLoanPayment,
    MonthlyCashFlow,
    BEPResult,
    CashBurnResult,
    FinancialScenarioResult,
)
from src.contracts.canonical_event import CanonicalEvent
from src.contracts.event_candidate import EvidenceRef, ExtractedEventCandidate
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.research import ResearchBundle, ResearchRequest
from src.contracts.source_document import SourceDocument
from src.contracts.store_signal import ScenarioAdjustment, StoreSignal

__all__ = [
    "StoreProfile",
    "MonthlyHistory",
    "MonthlyCostDetail",
    "MonthlyFixedCostDetail",
    "CostExposures",
    "Loan",
    "CustomPaymentSchedule",
    "MonthlyLoanPayment",
    "MonthlyCashFlow",
    "BEPResult",
    "CashBurnResult",
    "FinancialScenarioResult",
    "CanonicalEvent",
    "EvidenceRef",
    "ExtractedEventCandidate",
    "PolicyCandidate",
    "ResearchBundle",
    "ResearchRequest",
    "SourceDocument",
    "ScenarioAdjustment",
    "StoreSignal",
]
