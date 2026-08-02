from src.contracts.research import (
    AgentType,
    DocumentResearchOutcome,
    DocumentResearchStatus,
    ResearchBundle,
    ResearchRunStatus,
)
from src.orchestration.analysis_orchestrator import _research_summary
from src.orchestration.research_pipeline import ResearchPipelineResult
from tests.e2e.support import load_store


def test_research_funnel_uses_unique_outcome_ids_after_detail_routing():
    bundle = ResearchBundle(
        research_run_id="RUN-FUNNEL",
        agent_type=AgentType.LOCAL_EVENT,
        status=ResearchRunStatus.COMPLETED,
        source_document_ids=["SRC-LIST"],
        metadata={"usable_document_count": 99},
        document_outcomes=[
            DocumentResearchOutcome(
                source_id="SRC-LIST",
                agent_type=AgentType.LOCAL_EVENT,
                status=DocumentResearchStatus.STRUCTURED_LIST_TRAVERSED,
            ),
            DocumentResearchOutcome(
                source_id="SRC-DETAIL-ONE",
                agent_type=AgentType.LOCAL_EVENT,
                status=DocumentResearchStatus.NO_DISCRETE_EVENT,
                usable_for_extraction=True,
            ),
            DocumentResearchOutcome(
                source_id="SRC-DETAIL-TWO",
                agent_type=AgentType.LOCAL_EVENT,
                status=DocumentResearchStatus.CANDIDATES_EXTRACTED,
                usable_for_extraction=True,
            ),
        ],
    )

    summary = _research_summary(
        ResearchPipelineResult(run_id="RUN-FUNNEL", bundles=[bundle]),
        ResearchPipelineResult(run_id="RUN-FUNNEL"),
        [],
        load_store(),
    )

    assert summary.funnel.document_count == 3
    assert summary.funnel.usable_document_count == 2
    assert summary.funnel.usable_document_ratio == 2 / 3
