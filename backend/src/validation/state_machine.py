# Phase 10.1 implementation note.
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class EventValidationState(str, Enum):
    """Phase 10.1 documentation."""
    DISCOVERED = "DISCOVERED"
    FETCHED = "FETCHED"
    EXTRACTED = "EXTRACTED"
    SCHEMA_VALIDATED = "SCHEMA_VALIDATED"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    NORMALIZED = "NORMALIZED"
    TEMPORAL_GEO_VALIDATED = "TEMPORAL_GEO_VALIDATED"
    RELEVANCE_VALIDATED = "RELEVANCE_VALIDATED"
    DEDUPLICATED = "DEDUPLICATED"
    ACCEPTED = "ACCEPTED"
    
    # Implementation note.
    RETRYABLE = "RETRYABLE"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    REJECTED = "REJECTED"
    CONFLICTED = "CONFLICTED"

class StateTransitionRecord(BaseModel):
    from_state: EventValidationState
    to_state: EventValidationState
    reason: str
    failure_code: Optional[str] = None

class EventValidationContext(BaseModel):
    event_id: str
    current_state: EventValidationState = EventValidationState.DISCOVERED
    history: List[StateTransitionRecord] = Field(default_factory=list)

def transition_event_state(
    ctx: EventValidationContext,
    next_state: EventValidationState,
    reason: str,
    failure_code: Optional[str] = None,
) -> EventValidationContext:
    """Phase 10.1 documentation."""
    record = StateTransitionRecord(
        from_state=ctx.current_state,
        to_state=next_state,
        reason=reason,
        failure_code=failure_code,
    )
    ctx.history.append(record)
    ctx.current_state = next_state
    return ctx
