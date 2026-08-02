# Phase 12.5 implementation note.
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class CoefficientEntry(BaseModel):
    id: str
    impact_axis: str  # Implementation note.
    industry: str     # Implementation note.
    source_status: str # HISTORICAL_ESTIMATE, EXPERT_PRIOR, STRESS_ASSUMPTION, DISABLED
    baseline_beta: float = 0.0
    low_impact_beta: float = 0.03
    high_impact_beta: float = 0.08
    lower_bound: float = -0.15
    upper_bound: float = 0.15

COEFFICIENT_REGISTRY: Dict[str, CoefficientEntry] = {
    "COEF-ACCESS-FNB-v1": CoefficientEntry(
        id="COEF-ACCESS-FNB-v1",
        impact_axis="REVENUE_DEMAND",
        industry="FNB",
        source_status="STRESS_ASSUMPTION",
        baseline_beta=0.00,
        low_impact_beta=-0.03,
        high_impact_beta=-0.08,
        lower_bound=-0.15,
        upper_bound=0.15,
    )
}

def get_coefficient(coefficient_id: str) -> Optional[CoefficientEntry]:
    return COEFFICIENT_REGISTRY.get(coefficient_id)
