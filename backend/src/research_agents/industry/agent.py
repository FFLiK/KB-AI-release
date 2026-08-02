from src.contracts.research import AgentType, ResearchRequest
from src.research_agents.base import BaseResearchAgent


class IndustryResearchAgent(BaseResearchAgent):
    agent_type = AgentType.INDUSTRY
    extraction_domain = "INDUSTRY"
    prompt_version = "industry_extract.v1"

    def build_queries(self, request: ResearchRequest) -> list[str]:
        ingredients = " ".join(request.ingredient_categories) or "식자재"
        platforms = " ".join(request.platform_usage) or "배달 플랫폼"
        year = request.forecast_start.year
        return [
            f"site:kostat.go.kr {year} 외식업 수요 최근 공식 발표 {request.business_type_code}",
            f"site:mafra.go.kr OR site:at.or.kr 최근 {ingredients} 수급 도매가격 공고",
            f"{platforms} 공식 수수료 약관 변경 시행일",
            f"site:mfds.go.kr 최근 식품 회수 판매중지 {ingredients}",
            "site:ftc.go.kr 최근 외식업 플랫폼 규제 보도자료 시행",
        ]