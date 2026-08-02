# Phase 12.2 implementation note.
from typing import Dict

SOURCE_TIERS: Dict[str, float] = {
    "OFFICIAL_PRIMARY": 1.00,
    "OFFICIAL_LOCAL_GOV": 1.00,
    "FINANCIAL_INSTITUTION": 0.85,
    "OFFICIAL_SECONDARY": 0.90,
    "MAJOR_NEWS_WITH_PRIMARY_CITATION": 0.75,
    "MULTIPLE_INDEPENDENT_NEWS": 0.65,
    "MAJOR_NEWS": 0.40,
    "INDUSTRY_ASSOCIATION": 0.50,
    "OTHER": 0.00,
    "SINGLE_NEWS": 0.40,
    "COMMUNITY_OR_UNKNOWN": 0.00,
}

def calculate_evidence_score(
    source_tier: str = "OFFICIAL_PRIMARY",
    quote_validation: float = 1.0,
    temporal_validation: float = 1.0,
    conflict_penalty: float = 1.0,
) -> float:
    """
    Phase 12.2: Evidence = source_tier_score * quote_validation * temporal_validation * conflict_penalty
    """
    base_tier = SOURCE_TIERS.get(source_tier, 0.0)
    evidence = base_tier * quote_validation * temporal_validation * conflict_penalty
    return round(max(0.0, min(1.0, evidence)), 4)
