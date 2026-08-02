from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CorpusEvaluationMetrics:
    documents: int
    schema_success_rate: float
    event_precision: float
    event_recall: float
    event_f1: float
    evidence_span_exact_match_rate: float
    false_positive_rate: float
    validation_rejection_rate_by_code: dict[str, float]
    cost_per_accepted_event_usd: float
    latency_per_accepted_event_ms: float


class KoreanEventCorpusEvaluator:
    """Deterministic label-level evaluator; it never invokes a model."""

    def evaluate(self, corpus: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> CorpusEvaluationMetrics:
        if len(corpus) != len(predictions):
            raise ValueError("corpus and prediction counts must match")
        by_id = {str(item["case_id"]): item for item in predictions}
        if len(by_id) != len(predictions):
            raise ValueError("prediction case_id values must be unique")
        true_positive = false_positive = false_negative = 0
        schema_success = exact_spans = predicted_spans = accepted = 0
        total_cost = 0.0
        total_latency = 0.0
        rejection_counts: Counter[str] = Counter()
        for expected in corpus:
            predicted = by_id.get(str(expected["case_id"]), {})
            schema_success += int(bool(predicted.get("schema_valid")))
            expected_events = expected.get("events") or []
            predicted_events = predicted.get("events") or []
            unmatched = list(expected_events)
            for event in predicted_events:
                match = next(
                    (item for item in unmatched if item.get("event_type") == event.get("event_type")),
                    None,
                )
                if match is None:
                    false_positive += 1
                else:
                    true_positive += 1
                    unmatched.remove(match)
                    predicted_spans += 1
                    exact_spans += int(
                        event.get("evidence_quote") == match.get("evidence_quote")
                        and event.get("start_offset") == match.get("start_offset")
                        and event.get("end_offset") == match.get("end_offset")
                    )
                if event.get("accepted"):
                    accepted += 1
                for code in event.get("failure_codes") or []:
                    rejection_counts[str(code)] += 1
            false_negative += len(unmatched)
            total_cost += float(predicted.get("cost_usd") or 0)
            total_latency += float(predicted.get("latency_ms") or 0)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        total_predicted = true_positive + false_positive
        total_rejections = sum(rejection_counts.values())
        return CorpusEvaluationMetrics(
            documents=len(corpus),
            schema_success_rate=schema_success / len(corpus) if corpus else 1.0,
            event_precision=precision,
            event_recall=recall,
            event_f1=f1,
            evidence_span_exact_match_rate=exact_spans / predicted_spans if predicted_spans else 1.0,
            false_positive_rate=false_positive / total_predicted if total_predicted else 0.0,
            validation_rejection_rate_by_code={
                code: count / total_rejections for code, count in sorted(rejection_counts.items())
            },
            cost_per_accepted_event_usd=total_cost / accepted if accepted else 0.0,
            latency_per_accepted_event_ms=total_latency / accepted if accepted else 0.0,
        )
