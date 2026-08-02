from __future__ import annotations

from dataclasses import dataclass

from src.contracts.research import ReasoningLevel


@dataclass(frozen=True)
class RoutingContext:
    official_results: int = 1
    domains_in_scope: int = 1
    ambiguous_location_or_org: bool = False
    official_site_constrained: bool = False
    conflicting_official_sources: bool = False
    document_event_count_hint: int = 1
    has_relative_dates: bool = False
    distributed_across_attachments: bool = False
    failure_codes: tuple[str, ...] = ()
    policy_revision_chain: bool = False


class ModelRouter:
    SEARCH_MODEL = "gemini-3.6-flash"
    EXTRACTION_MODEL = "gpt-5.6-terra"

    def route_search(self, context: RoutingContext) -> ReasoningLevel:
        if context.official_results == 0 or context.ambiguous_location_or_org or context.domains_in_scope > 1:
            return ReasoningLevel.HIGH
        if context.official_site_constrained:
            return ReasoningLevel.LOW
        return ReasoningLevel.MEDIUM

    def route_extraction(self, context: RoutingContext) -> ReasoningLevel:
        if context.conflicting_official_sources or context.policy_revision_chain:
            return ReasoningLevel.HIGH
        if (context.document_event_count_hint >= 2 or context.has_relative_dates or
            context.distributed_across_attachments or context.failure_codes):
            return ReasoningLevel.MEDIUM
        return ReasoningLevel.LOW
