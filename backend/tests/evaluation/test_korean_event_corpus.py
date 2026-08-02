import json
from pathlib import Path

from src.evaluation.corpus_evaluator import KoreanEventCorpusEvaluator


CORPUS_PATH = Path("tests/fixtures/research_documents/korean_event_corpus.v1.json")


def load_corpus() -> list[dict]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def test_corpus_has_twenty_reviewed_korean_documents_and_exact_offsets() -> None:
    corpus = load_corpus()
    assert len(corpus) == 20
    assert {item["domain"] for item in corpus} == {"MACRO", "INDUSTRY", "LOCAL", "POLICY"}
    assert any(len(item["events"]) > 1 for item in corpus)
    assert any("PROMPT_INJECTION_DETECTED" in item["rejection_codes"] for item in corpus)
    assert any(not item["event_present"] for item in corpus)
    for case in corpus:
        assert case["review_status"] == "MANUALLY_REVIEWED_V1"
        for event in case["events"]:
            assert case["body_text"][event["start_offset"]:event["end_offset"]] == event["evidence_quote"]


def test_generator_output_matches_committed_corpus() -> None:
    from scripts.generate_korean_event_corpus import build_corpus

    assert load_corpus() == build_corpus()


def test_metric_harness_reports_schema_events_evidence_rejections_cost_and_latency() -> None:
    corpus = load_corpus()
    predictions = []
    for case in corpus:
        events = []
        for event in case["events"]:
            events.append({
                **event,
                "accepted": case["accept_expected"],
                "failure_codes": case["rejection_codes"],
            })
        predictions.append({
            "case_id": case["case_id"],
            "schema_valid": True,
            "events": events,
            "cost_usd": 0.01,
            "latency_ms": 100,
        })

    metrics = KoreanEventCorpusEvaluator().evaluate(corpus, predictions)

    assert metrics.documents == 20 and metrics.schema_success_rate == 1
    assert metrics.event_precision == metrics.event_recall == metrics.event_f1 == 1
    assert metrics.evidence_span_exact_match_rate == 1 and metrics.false_positive_rate == 0
    assert set(metrics.validation_rejection_rate_by_code) == {
        "GEO_NOT_FOUND", "MECHANISM_NOT_ALLOWED", "TEMPORAL_INVALID", "PROMPT_INJECTION_DETECTED"
    }
    assert metrics.cost_per_accepted_event_usd > 0
    assert metrics.latency_per_accepted_event_ms > 0
