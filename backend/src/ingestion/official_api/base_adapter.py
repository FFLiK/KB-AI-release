"""Common fail-closed contract for official API adapters."""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ProviderContractError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CanonicalObservation(BaseModel):
    """Legacy adapter output converted to the versioned official contract by the pipeline."""

    model_config = ConfigDict(extra="forbid")

    indicator_id: str
    value: float
    unit: str
    frequency: str
    observed_at: str
    released_at: str | None = None
    available_at: str | None = None
    source_id: str
    revision_id: str | None = None
    normalization_version: str = "indicator.v1"
    availability_policy_id: str | None = None
    assumptions: list[str] = Field(default_factory=list)


def provider_failure_code(exc: Exception) -> str:
    if isinstance(exc, ProviderContractError):
        return exc.code
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in {401, 403}:
            return "AUTHENTICATION_FAILED"
        if exc.code == 429:
            return "RATE_LIMITED"
        return f"HTTP_{exc.code}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "TIMEOUT"
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return "MALFORMED_RESPONSE"
    return "PROVIDER_FAILURE"


class BaseOfficialApiAdapter(ABC):
    last_error_code: str | None = None

    @abstractmethod
    def fetch(self, request_params: Dict[str, Any]) -> Any: ...

    @abstractmethod
    def parse(self, raw_response: Any) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def normalize(self, raw_observations: List[Dict[str, Any]]) -> List[CanonicalObservation]: ...

    def process(self, request_params: Dict[str, Any]) -> List[CanonicalObservation]:
        self.last_error_code = None
        try:
            raw = self.fetch(request_params)
            parsed = self.parse(raw)
            if not parsed:
                self.last_error_code = "EMPTY_RESPONSE"
                return []
            return self.normalize(parsed)
        except Exception as exc:
            self.last_error_code = provider_failure_code(exc)
            logger.warning(
                "Official provider failed closed: code=%s type=%s",
                self.last_error_code,
                type(exc).__name__,
            )
            return []
