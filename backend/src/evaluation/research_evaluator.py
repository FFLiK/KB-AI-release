from __future__ import annotations

from dataclasses import dataclass

from src.contracts.event_candidate import ExtractedEventCandidate
from src.contracts.source_document import SourceDocument
from src.validation.evidence_validator import validate_event_evidence


@dataclass(frozen=True)
class EvaluationMetrics:
    documents:int; schema_pass_rate:float; event_presence_f1:float; event_type_accuracy:float; valid_evidence_rate:float; unsupported_fact_rate:float


class ResearchEvaluator:
    """Deterministic evaluation harness shared by cloud and local extractors."""
    def evaluate(self,predictions:list[list[ExtractedEventCandidate]],gold:list[list[ExtractedEventCandidate]],documents:list[SourceDocument])->EvaluationMetrics:
        if not (len(predictions)==len(gold)==len(documents)): raise ValueError("prediction, gold, and document counts must match")
        tp=fp=fn=correct_type=evidence_total=evidence_valid=unsupported=0
        for predicted,expected,document in zip(predictions,gold,documents):
            pred_has=bool(predicted); gold_has=bool(expected)
            tp+=int(pred_has and gold_has); fp+=int(pred_has and not gold_has); fn+=int(not pred_has and gold_has)
            expected_types={str(x.event_type) for x in expected}
            correct_type+=sum(str(x.event_type) in expected_types for x in predicted)
            for item in predicted:
                evidence_total+=len(item.evidence)
                ok,_=validate_event_evidence([e.model_dump() for e in item.evidence],{document.source_id:document.body_text})
                evidence_valid+=len(item.evidence) if ok else 0
                unsupported+=0 if ok else 1
        precision=tp/(tp+fp) if tp+fp else 1.0; recall=tp/(tp+fn) if tp+fn else 1.0; f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
        total_pred=sum(map(len,predictions))
        return EvaluationMetrics(len(documents),1.0,f1,correct_type/total_pred if total_pred else 1.0,evidence_valid/evidence_total if evidence_total else 1.0,unsupported/total_pred if total_pred else 0.0)
