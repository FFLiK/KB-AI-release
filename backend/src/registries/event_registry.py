from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.contracts.event_candidate import ExtractedEventCandidate


class RegistryValidationError(ValueError):
    def __init__(self, codes: list[str]):
        self.codes = codes
        super().__init__(", ".join(codes))


class EventRegistry:
    def __init__(self, path: str | Path | None = None):
        registry_path = Path(path) if path else Path(__file__).with_name("event_types.v1.yaml")
        with registry_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
        self.version: str = payload["version"]
        self.events: dict[str, dict[str, Any]] = payload["event_types"]

    def get(self, event_type: str) -> dict[str, Any]:
        try:
            return self.events[event_type]
        except KeyError as exc:
            raise RegistryValidationError(["ENUM_NOT_ALLOWED"]) from exc

    def signal_eligibility(self, event_type: str) -> tuple[bool, str]:
        config = self.get(event_type)
        enabled = bool(config.get("signal_enabled", True))
        if enabled:
            return True, "This event type is eligible to generate a financial signal."
        return False, str(
            config.get("signal_disabled_reason")
            or f"{event_type} is reference-only under {self.version} and does not generate financial signals."
        )

    def validate_candidate(self, candidate: ExtractedEventCandidate) -> None:
        config = self.get(getattr(candidate.event_type, "value", candidate.event_type))
        codes: list[str] = []
        if candidate.event_family != config["family"] or getattr(candidate.domain, "value", candidate.domain) != config["domain"]:
            codes.append("ENUM_NOT_ALLOWED")
        for impact in candidate.impacts:
            axis = getattr(impact.axis, "value", impact.axis)
            if axis not in config["allowed_axes"]:
                codes.append("DIRECTION_MECHANISM_NOT_ALLOWED")
            if impact.mechanism not in config["allowed_mechanisms"]:
                codes.append("MECHANISM_NOT_SUPPORTED")
            if getattr(impact.direction, "value", impact.direction) not in config.get("allowed_directions", {}).get(axis, []):
                codes.append("DIRECTION_MECHANISM_NOT_ALLOWED")
        for attribute in config.get("required_attributes", []):
            if candidate.attributes.get(attribute) in (None, "", []):
                codes.append("MISSING_REQUIRED_FIELD")
        if codes:
            raise RegistryValidationError(sorted(set(codes)))


@lru_cache(maxsize=1)
def default_registry() -> EventRegistry:
    return EventRegistry()
