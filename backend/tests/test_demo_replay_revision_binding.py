from pathlib import Path

from src.config.settings import Settings
from src.contracts.research import ReasoningLevel
from src.providers.demo_replay import DemoReplayCorpus, DemoReplayEventExtractor


def test_demo_event_evidence_uses_run_specific_persisted_revisions() -> None:
    demo_root = Path(__file__).resolve().parents[2] / "demo"
    corpus = DemoReplayCorpus(Settings(
        enable_demo_datasets=True,
        demo_dataset_id="cafe-import-cost-shock.v1",
        demo_dataset_root=demo_root,
    ))
    extractor = DemoReplayEventExtractor(corpus)
    news_id = "SRC-DEMO-COFFEE-COST-NEWS"
    bulletin_id = "SRC-DEMO-COFFEE-COST-BULLETIN"
    news = corpus.documents[news_id].model_copy(update={"revision_id": "REV-RUNTIME-NEWS"})
    bulletin = corpus.documents[bulletin_id].model_copy(update={"revision_id": "REV-RUNTIME-BULLETIN"})

    first = extractor.extract(news, "RUN-A", "INDUSTRY", ReasoningLevel.HIGH)
    second = extractor.extract(bulletin, "RUN-A", "INDUSTRY", ReasoningLevel.HIGH)

    assert first.candidates == []
    assert len(second.candidates) == 1
    assert {(item.source_id, item.source_revision_id) for item in second.candidates[0].evidence} == {
        (news_id, "REV-RUNTIME-NEWS"),
        (bulletin_id, "REV-RUNTIME-BULLETIN"),
    }

    other_run_first = extractor.extract(bulletin, "RUN-B", "INDUSTRY", ReasoningLevel.HIGH)
    other_run_second = extractor.extract(news, "RUN-B", "INDUSTRY", ReasoningLevel.HIGH)

    assert other_run_first.candidates == []
    assert len(other_run_second.candidates) == 1
