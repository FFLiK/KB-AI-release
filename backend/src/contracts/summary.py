"""Machine-verifiable grounded summary contracts."""
from typing import Any

from pydantic import Field

from src.contracts.research import StrictModel


class GroundedStatement(StrictModel):
    statement_id: str
    text: str
    citation_ids: list[str] = Field(min_length=1)
    facts: dict[str, Any] = Field(default_factory=dict)


class GroundedSummary(StrictModel):
    summary_id: str
    result_id: str
    statements: list[GroundedStatement] = Field(default_factory=list)
    validation_status: str
    validation_errors: list[str] = Field(default_factory=list)
    version: str = "grounded_summary.v1"

