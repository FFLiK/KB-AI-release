# Phase 19.3 implementation note.
from decimal import Decimal
from typing import Dict, List, Any, Optional

from src.contracts.store import StoreProfile
from src.contracts.financial import FinancialScenarioResult
from src.finance.scenario import run_financial_scenario
from src.relief.benefit_simulator import ReliefBenefitComparison

class DeterministicChatbotToolHandler:
    """Phase 19.3 documentation."""

    def __init__(self, current_report_payload: Any = None):
        self.payload = current_report_payload

    def get_result(self, result_id: str) -> Dict[str, Any]:
        """Phase 19.3: get_result(result_id)"""
        try:
            if not result_id or not isinstance(result_id, str):
                return {"status": "ERROR", "message": "Invalid or missing result_id parameter"}
            
            if self.payload and self.payload.run_id == result_id:
                return {"status": "SUCCESS", "data": self.payload.model_dump()}
            
            return {"status": "NOT_FOUND", "message": f"Result for ID '{result_id}' not found"}
        except Exception as e:
            return {"status": "ERROR", "message": f"Unexpected error in get_result: {str(e)}"}

    def run_what_if(
        self,
        store_profile: StoreProfile,
        revenue_delta: float = 0.0,
        interest_delta: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Phase 19.3: run_what_if(store_id, parameter_changes)
        """
        try:
            if not store_profile or not isinstance(store_profile, StoreProfile):
                return {"status": "ERROR", "message": "Invalid store_profile object"}

            # Implementation note.
            r_delta = float(revenue_delta) if revenue_delta is not None else 0.0
            i_delta = float(interest_delta) if interest_delta is not None else 0.0

            rev_mult = Decimal(str(round(1.0 + r_delta, 4)))
            int_delta = Decimal(str(round(i_delta, 4)))

            scenario_res = run_financial_scenario(
                store_profile=store_profile,
                scenario_name="WHAT_IF",
                revenue_multiplier=rev_mult,
                interest_rate_delta=int_delta,
            )
            return {"status": "SUCCESS", "data": scenario_res.model_dump()}
        except Exception as e:
            return {"status": "ERROR", "message": f"Failed to execute what-if simulation: {str(e)}"}

    def compare_relief_options(
        self, relief_options: List[ReliefBenefitComparison]
    ) -> List[Dict[str, Any]]:
        """Phase 19.3: compare_relief_options(policy_ids)"""
        try:
            if not relief_options or not isinstance(relief_options, list):
                return []
            return [opt.model_dump() for opt in relief_options if isinstance(opt, ReliefBenefitComparison)]
        except Exception:
            return []
