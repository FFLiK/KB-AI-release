from __future__ import annotations

from dataclasses import dataclass

from src.config.settings import Settings
from src.extraction.model_router import ModelRouter
from src.normalization.geo_normalizer import MapApiGeocoder
from src.orchestration.research_pipeline import ResearchPipeline
from src.providers.extraction.fake import FakeEventExtractor
from src.providers.extraction.openai import OpenAIEventExtractor
from src.providers.extraction.local import LocalEventExtractor
from src.providers.extraction.policy import FakePolicyExtractor,OpenAIPolicyExtractor
from src.providers.demo_replay import (
    DemoReplayCorpus,DemoReplayDocumentFetcher,DemoReplayEventExtractor,DemoReplaySearchProvider,
)
from src.providers.search.fake import FakeSearchProvider
from src.providers.search.gemini import GeminiSearchProvider
from src.research_agents.industry.agent import IndustryResearchAgent
from src.research_agents.local_event.agent import LocalEventResearchAgent
from src.research_agents.macro.agent import MacroResearchAgent
from src.research_agents.policy_regulation.agent import PolicyRegulationResearchAgent
from src.source_snapshot.fetcher import HttpDocumentFetcher
from src.storage import AuditRepository,Database,EventRepository,PolicyRepository,SourceRepository
from src.validation.research_validator import ResearchEventValidator


@dataclass
class ResearchServices:
    database:Database; pipeline:ResearchPipeline; sources:SourceRepository; events:EventRepository; policies:PolicyRepository; audit:AuditRepository


def build_services(settings:Settings|None=None,force_fake:bool=False)->ResearchServices:
    settings=settings or Settings()
    mode="fake" if force_fake else settings.provider_mode
    if mode not in {"auto","fake","real","local","demo_replay"}: raise ValueError(f"Unsupported RESEARCH_PROVIDER_MODE: {mode}")
    if mode=="real" and not (settings.gemini_api_key and settings.openai_api_key):
        raise ValueError("real mode requires GEMINI_API_KEY and OPENAI_API_KEY")
    if mode=="local" and not (settings.gemini_api_key and settings.openai_api_key and settings.local_llm_base_url):
        raise ValueError("local mode requires GEMINI_API_KEY, OPENAI_API_KEY, and LOCAL_LLM_BASE_URL")
    db=Database(settings.database_url); db.initialize_schema(settings.schema_mode)
    sources=SourceRepository(db); events=EventRepository(db); policies=PolicyRepository(db); audit=AuditRepository(db); router=ModelRouter()
    use_fake=mode=="fake" or (mode=="auto" and not (settings.gemini_api_key and settings.openai_api_key))
    search=FakeSearchProvider() if use_fake else GeminiSearchProvider(settings)
    extractor=FakeEventExtractor() if use_fake else LocalEventExtractor(settings) if mode=="local" else OpenAIEventExtractor(settings)
    policy_extractor=FakePolicyExtractor() if use_fake else OpenAIPolicyExtractor(settings)
    fetcher=HttpDocumentFetcher(settings)
    if mode=="demo_replay":
        corpus=DemoReplayCorpus(settings)
        search=DemoReplaySearchProvider(corpus)
        fetcher=DemoReplayDocumentFetcher(corpus)
        extractor=DemoReplayEventExtractor(corpus)
        policy_extractor=FakePolicyExtractor()
    common=dict(search=search,fetcher=fetcher,extractor=extractor,source_repo=sources,event_repo=events,audit_repo=audit,router=router,settings=settings)
    agents=[MacroResearchAgent(**common),IndustryResearchAgent(**common),LocalEventResearchAgent(**common),PolicyRegulationResearchAgent(**common,policy_extractor=policy_extractor,policy_repo=policies)]
    if mode=="demo_replay":
        agents=[agent for agent in agents if agent.extraction_domain in corpus.target_domains]
    pipeline=ResearchPipeline(agents,ResearchEventValidator(geocoder=MapApiGeocoder()),events,policies,audit)
    return ResearchServices(db,pipeline,sources,events,policies,audit)
