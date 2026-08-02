"""Loader for versioned official indicator and availability policies."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=1)
def load_official_indicator_registry() -> dict[str, dict[str, Any]]:
    path = Path(__file__).with_name("official_indicators.v1.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(payload.get("indicators") or {})


def provider_indicators(provider: str) -> dict[str, dict[str, Any]]:
    normalized = provider.upper()
    return {
        indicator_id: definition
        for indicator_id, definition in load_official_indicator_registry().items()
        if str(definition.get("provider", "")).upper() == normalized
    }
