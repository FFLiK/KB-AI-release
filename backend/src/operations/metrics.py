"""Small dependency-free metrics boundary for API and pipeline operations."""
from __future__ import annotations

from collections import defaultdict
from threading import Lock


class MetricsRegistry:
    def __init__(self):
        self._lock = Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._samples: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            samples = self._samples[name]
            samples.append(float(value))
            if len(samples) > 1000:
                del samples[:-1000]



    def record_replay_comparison(self, expected_hash: str, actual_hash: str) -> None:
        self.increment("deterministic_replay_comparison_total")
        if expected_hash != actual_hash:
            self.increment("deterministic_replay_mismatch_total")

    def reset(self) -> None:
        """Clear in-memory state; intended for isolated tests and worker startup."""
        with self._lock:
            self._counters.clear()
            self._samples.clear()
            self._gauges.clear()

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
        return ordered[index]

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters = dict(self._counters)
            samples = {key: list(value) for key, value in self._samples.items()}
            gauges = dict(self._gauges)
        distributions = {
            name: {
                "count": len(values),
                "p50": self._percentile(values, 0.50),
                "p95": self._percentile(values, 0.95),
            }
            for name, values in samples.items()
        }
        required = (
            "analysis_completed_total",
            "analysis_partial_total",
            "analysis_failed_total",
            "official_provider_requests_total",
            "official_provider_failure_total",
            "official_provider_empty_result_total",
            "official_records_fetched_total",
            "official_records_accepted_total",
            "official_records_rejected_total",
            "official_missing_indicator_total",
            "research_fetch_failure_total",
            "research_search_input_tokens_total",
            "research_search_output_tokens_total",
            "research_extraction_input_tokens_total",
            "research_extraction_output_tokens_total",
            "extraction_schema_failure_total",
            "evidence_rejection_total",
            "event_accepted_total",
            "event_rejected_total",
            "duplicate_conflict_total",
            "model_fallback_total",
            "policy_unknown_or_closed_total",
            "queue_retry_total",
            "deterministic_replay_comparison_total",
            "deterministic_replay_mismatch_total",
        )
        for name in required:
            counters.setdefault(name, 0)
        event_total = counters["event_accepted_total"] + counters["event_rejected_total"]
        gauges.setdefault(
            "event_acceptance_ratio",
            counters["event_accepted_total"] / event_total if event_total else 0.0,
        )
        return {
            "counters": counters,
            "gauges": gauges,
            "distributions": distributions,
        }


metrics = MetricsRegistry()
