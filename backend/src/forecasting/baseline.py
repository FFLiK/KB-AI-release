from decimal import Decimal
from typing import List

from src.contracts.store import MonthlyHistory


class NaiveBaselineModel:
    """Recent-mean compatibility baseline without a synthetic revenue default."""

    def predict_revenue(self, history: List[MonthlyHistory], horizon: int) -> List[Decimal]:
        if not history:
            raise ValueError("INSUFFICIENT_DATA: history is required for a revenue baseline")
        recent_revenues = [item.revenue_krw for item in history[-6:]]
        average = sum(recent_revenues) / Decimal(len(recent_revenues))
        return [average] * horizon
