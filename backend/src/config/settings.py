from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from src.config.credential_validation import get_credential


def load_application_env() -> None:
    """Load the application dotenv unless an isolated test process disables it."""
    if os.getenv("KB_AI_SKIP_DOTENV") != "1":
        load_dotenv()


load_application_env()


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


def _env_flag(key: str, default: str = "0") -> bool:
    return _env(key, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    provider_mode: str = field(default_factory=lambda: _env("RESEARCH_PROVIDER_MODE", "auto").lower())
    enable_demo_datasets: bool = field(default_factory=lambda: _env_flag("ENABLE_DEMO_DATASETS"))
    demo_dataset_id: str | None = field(default_factory=lambda: _env("DEMO_DATASET_ID", "").strip() or None)
    demo_dataset_root: Path | None = field(default_factory=lambda: (
        Path(value).expanduser()
        if (value := _env("DEMO_DATASET_ROOT", "").strip()) else None
    ))
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development").lower())
    official_data_provider_mode: str = field(
        default_factory=lambda: _env("OFFICIAL_DATA_PROVIDER_MODE", "auto").lower()
    )
    database_url: str = field(
        default_factory=lambda: _env("RESEARCH_DATABASE_URL", "sqlite:///./data/research.db")
    )
    schema_mode: str = field(default_factory=lambda: _env("DB_SCHEMA_MODE", "auto").lower())
    snapshot_dir: Path = field(
        default_factory=lambda: Path(_env("SOURCE_SNAPSHOT_DIR", "./data/source_snapshots"))
    )
    gemini_api_key: str | None = field(default_factory=lambda: get_credential("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_SEARCH_MODEL", "gemini-3.6-flash"))
    gemini_timeout_seconds: float = field(
        default_factory=lambda: float(_env(
            "RESEARCH_SEARCH_REQUEST_TIMEOUT_SECONDS",
            _env("GEMINI_TIMEOUT_SECONDS", "90"),
        ))
    )
    nvidia_api_key: str | None = field(default_factory=lambda: get_credential("NVIDIA_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: get_credential("OPENAI_API_KEY"))
    openai_base_url: str = field(
        default_factory=lambda: _env(
            "OPENAI_BASE_URL",
            "https://integrate.api.nvidia.com/v1" if get_credential("NVIDIA_API_KEY") and not get_credential("OPENAI_API_KEY") else "https://api.openai.com/v1"
        )
    )
    openai_model: str = field(
        default_factory=lambda: _env(
            "OPENAI_EXTRACTION_MODEL",
            "meta/llama-3.3-70b-instruct" if get_credential("NVIDIA_API_KEY") and not get_credential("OPENAI_API_KEY") else "gpt-5.6-terra"
        )
    )
    openai_max_output_tokens: int = field(
        default_factory=lambda: int(_env("OPENAI_MAX_OUTPUT_TOKENS", "6000"))
    )
    openai_timeout_seconds: float = field(
        default_factory=lambda: float(_env(
            "RESEARCH_EXTRACTION_REQUEST_TIMEOUT_SECONDS",
            _env("OPENAI_TIMEOUT_SECONDS", "180"),
        ))
    )
    local_llm_base_url: str | None = field(
        default_factory=lambda: get_credential("LOCAL_LLM_BASE_URL") or (get_credential("NVIDIA_API_KEY") and "https://integrate.api.nvidia.com/v1" or None)
    )
    local_llm_model: str = field(
        default_factory=lambda: _env(
            "LOCAL_LLM_MODEL",
            "meta/llama-3.3-70b-instruct" if get_credential("NVIDIA_API_KEY") else "qwen3.5-27b"
        )
    )
    http_timeout_seconds: float = field(default_factory=lambda: float(_env(
        "RESEARCH_DOCUMENT_FETCH_TIMEOUT_SECONDS",
        _env("RESEARCH_HTTP_TIMEOUT_SECONDS", "30"),
    )))
    research_agent_wall_clock_limit_seconds: float = field(
        default_factory=lambda: float(_env("RESEARCH_AGENT_WALL_CLOCK_LIMIT_SECONDS", "0"))
    )
    analysis_job_timeout_seconds: float = field(
        default_factory=lambda: float(_env("ANALYSIS_JOB_TIMEOUT_SECONDS", "1800"))
    )
    research_min_documents_after_discovery: int = field(
        default_factory=lambda: int(_env("RESEARCH_MIN_DOCUMENTS_AFTER_DISCOVERY", "3"))
    )
    research_official_seed_reserve: int = field(
        default_factory=lambda: int(_env("RESEARCH_OFFICIAL_SEED_RESERVE", "2"))
    )
    max_document_bytes: int = field(default_factory=lambda: int(_env("RESEARCH_MAX_DOCUMENT_BYTES", "5242880")))
    max_redirects: int = field(default_factory=lambda: int(_env("RESEARCH_MAX_REDIRECTS", "3")))
    max_search_retries: int = field(default_factory=lambda: int(_env("RESEARCH_MAX_SEARCH_RETRIES", "1")))
    max_extraction_retries: int = field(default_factory=lambda: int(_env("RESEARCH_MAX_EXTRACTION_RETRIES", "1")))
    max_local_child_pages: int = field(default_factory=lambda: int(_env("RESEARCH_MAX_LOCAL_CHILD_PAGES", "6")))
    job_runner_mode: str = field(default_factory=lambda: _env("JOB_RUNNER_MODE", "in_process").lower())
    result_retention_days: int = field(default_factory=lambda: int(_env("RESULT_RETENTION_DAYS", "365")))
    raw_snapshot_retention_days: int = field(default_factory=lambda: int(_env("RAW_SNAPSHOT_RETENTION_DAYS", "90")))
    auth_mode: str = field(default_factory=lambda: _env("API_AUTH_MODE", "none").lower())
    tenant_mode: str = field(default_factory=lambda: _env("TENANT_MODE", "single").lower())
    rate_limit_per_minute: int = field(default_factory=lambda: int(_env("RATE_LIMIT_PER_MINUTE", "0")))
    forecast_min_improvement: str = field(default_factory=lambda: _env("FORECAST_MIN_IMPROVEMENT", "0"))
    forecast_backtest_windows: int = field(default_factory=lambda: int(_env("FORECAST_BACKTEST_WINDOWS", "12")))

    def __post_init__(self) -> None:
        timeout_values = {
            "RESEARCH_AGENT_WALL_CLOCK_LIMIT_SECONDS": self.research_agent_wall_clock_limit_seconds,
            "RESEARCH_SEARCH_REQUEST_TIMEOUT_SECONDS": self.gemini_timeout_seconds,
            "RESEARCH_DOCUMENT_FETCH_TIMEOUT_SECONDS": self.http_timeout_seconds,
            "RESEARCH_EXTRACTION_REQUEST_TIMEOUT_SECONDS": self.openai_timeout_seconds,
            "ANALYSIS_JOB_TIMEOUT_SECONDS": self.analysis_job_timeout_seconds,
        }
        if self.research_agent_wall_clock_limit_seconds < 0:
            raise ValueError("RESEARCH_AGENT_WALL_CLOCK_LIMIT_SECONDS must be zero or positive")
        for name, value in timeout_values.items():
            if name != "RESEARCH_AGENT_WALL_CLOCK_LIMIT_SECONDS" and value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if self.research_min_documents_after_discovery <= 0:
            raise ValueError("RESEARCH_MIN_DOCUMENTS_AFTER_DISCOVERY must be greater than zero")
        if self.research_official_seed_reserve < 0:
            raise ValueError("RESEARCH_OFFICIAL_SEED_RESERVE must be zero or positive")
        if self.max_local_child_pages <= 0:
            raise ValueError("RESEARCH_MAX_LOCAL_CHILD_PAGES must be greater than zero")
