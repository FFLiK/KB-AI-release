from pathlib import Path

import pytest

from src.config.settings import Settings
from src.orchestration.factory import build_services
from src.providers.extraction.local import LocalEventExtractor
from src.providers.extraction.policy import OpenAIPolicyExtractor


def test_local_mode_wires_gemini_local_events_and_gpt_policy(tmp_path:Path):
    settings=Settings(provider_mode="local",database_url=f"sqlite:///{(tmp_path/'local.db').as_posix()}",
        snapshot_dir=tmp_path/"snapshots",gemini_api_key="test-gemini",openai_api_key="test-openai",
        local_llm_base_url="http://127.0.0.1:9000")
    services=build_services(settings)
    assert isinstance(services.pipeline.agents[0].extractor,LocalEventExtractor)
    policy_agent=services.pipeline.agents[-1]
    assert isinstance(policy_agent.policy_extractor,OpenAIPolicyExtractor)


def test_explicit_real_mode_fails_closed_without_credentials(tmp_path:Path):
    settings=Settings(provider_mode="real",database_url=f"sqlite:///{(tmp_path/'real.db').as_posix()}",
        gemini_api_key=None,openai_api_key=None)
    with pytest.raises(ValueError,match="requires GEMINI_API_KEY"):
        build_services(settings)
    assert not (tmp_path/"real.db").exists()
