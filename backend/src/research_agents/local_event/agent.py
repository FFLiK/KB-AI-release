from src.contracts.research import AgentType, ResearchRequest
from src.research_agents.base import BaseResearchAgent


class LocalEventResearchAgent(BaseResearchAgent):
    agent_type = AgentType.LOCAL_EVENT
    extraction_domain = "LOCAL"
    prompt_version = "local_event_extract.v1"

    def build_queries(self, request: ResearchRequest) -> list[str]:
        area = request.store_location.administrative_area or request.store_location.address
        year = request.forecast_start.year
        return [
            f"{area} {year} 도로 공사 교통 통제 지자체 공고",
            f"{area} 최근 보행로 통제 공사 기간 공식",
            f"{area} {year} 축제 행사 일정 공식",
            f"{area} 최근 지하철 버스 운행 변경 공식",
            f"{area} {year} 주요 시설 개장 폐점 공식",
            f"{area} 최근 재난 대피 영업 제한 공식",
            f"{area} 상권 {request.business_type_code} 개업 폐업 공공데이터",
            f"{area} 최근 주차장 통제 기간 공식",
        ]