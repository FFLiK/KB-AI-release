# Phase 19.1 implementation note.
from decimal import Decimal
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from src.contracts.store import StoreProfile
from src.contracts.financial import FinancialScenarioResult
from src.relief.benefit_simulator import ReliefBenefitComparison

class DeterministicReportPayload(BaseModel):
    """Phase 19.1 documentation."""
    run_id: str
    store_id: str
    as_of_date: str
    current_cash_krw: Decimal
    minimum_operating_cash_krw: Decimal
    baseline_scenario: FinancialScenarioResult
    low_impact_scenario: Optional[FinancialScenarioResult] = None
    high_impact_scenario: Optional[FinancialScenarioResult] = None
    relief_options: List[ReliefBenefitComparison] = Field(default_factory=list)
    version_info: Dict[str, str] = Field(default_factory=dict)

def render_deterministic_report(
    run_id: str,
    store_profile: StoreProfile,
    as_of_date: str,
    baseline_scenario: FinancialScenarioResult,
    low_impact_scenario: Optional[FinancialScenarioResult] = None,
    high_impact_scenario: Optional[FinancialScenarioResult] = None,
    relief_options: List[ReliefBenefitComparison] = None,
) -> DeterministicReportPayload:
    """Phase 19.1 documentation."""
    return DeterministicReportPayload(
        run_id=run_id,
        store_id=store_profile.store_id,
        as_of_date=as_of_date,
        current_cash_krw=store_profile.current_cash_krw,
        minimum_operating_cash_krw=store_profile.minimum_operating_cash_krw,
        baseline_scenario=baseline_scenario,
        low_impact_scenario=low_impact_scenario,
        high_impact_scenario=high_impact_scenario,
        relief_options=relief_options or [],
        version_info={
            "schema_version": "store_profile.v1",
            "calculation_version": "signal.v1",
            "report_version": "deterministic.v1",
        },
    )
