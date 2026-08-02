from src.contracts.research import AgentType, ResearchRequest
from src.research_agents.base import BaseResearchAgent


class MacroResearchAgent(BaseResearchAgent):
    agent_type = AgentType.MACRO
    extraction_domain = "MACRO"
    prompt_version = "macro_extract.v1"

    def build_queries(self, request: ResearchRequest) -> list[str]:
        year = request.forecast_start.year
        ingredients = " ".join(request.ingredient_categories) or "수입 식자재"
        return [
            f"site:bok.or.kr {year} 통화정책방향 기준금리 결정 보도자료",
            f"site:moef.go.kr OR site:kostat.go.kr {year} 최근 내수 전망 공식 발표",
            f"site:customs.go.kr OR site:mafra.go.kr 최근 {ingredients} 공급 차질 회복 공식",
            f"site:motie.go.kr {year} 원달러 공급망 전망 공식 발표",
        ]