# signals package initialization
from src.signals.evidence_score import calculate_evidence_score
from src.signals.exposure_score import calculate_exposure_score
from src.signals.severity_registry import get_event_severity
from src.signals.coefficient_registry import get_coefficient
from src.signals.aggregator import calculate_raw_signal, aggregate_signals_to_multiplier

__all__ = [
    "calculate_evidence_score",
    "calculate_exposure_score",
    "get_event_severity",
    "get_coefficient",
    "calculate_raw_signal",
    "aggregate_signals_to_multiplier",
]
