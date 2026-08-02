"""Deterministic, source-scoped identifiers for extracted records."""
from __future__ import annotations

import hashlib
import re
import unicodedata


def _token(value: str, *, limit: int) -> str:
    normalized = unicodedata.normalize("NFKC", value).upper()
    normalized = re.sub(r"[^0-9A-Z]+", "-", normalized).strip("-") or "UNKNOWN"
    if len(normalized) <= limit:
        return normalized
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10].upper()
    return f"{normalized[:limit - len(digest) - 1]}-{digest}"


def _source_token(source_id: str, source_revision_id: str | None) -> str:
    material = f"{source_id}|{source_revision_id or ''}".encode("utf-8")
    return "SRC" + hashlib.sha256(material).hexdigest()[:10].upper()


def event_candidate_id(
    research_run_id: str,
    agent_type: str,
    source_id: str,
    source_revision_id: str | None,
    source_local_index: int,
    *,
    retry_attempt: int = 0,
) -> str:
    """Return a stable ID unique to one run, agent, source revision, and index."""
    if source_local_index < 1:
        raise ValueError("source_local_index must start at one")
    parts = [
        "EVC",
        _token(research_run_id, limit=25),
        _token(agent_type, limit=10),
        _source_token(source_id, source_revision_id),
    ]
    if retry_attempt:
        parts.append(f"R{retry_attempt}")
    parts.append(f"{source_local_index:03d}")
    return "-".join(parts)


def policy_extractor_id(
    research_run_id: str,
    source_id: str,
    source_revision_id: str | None,
    source_local_index: int,
) -> str:
    """Return a stable ID for source-specific policy extraction provenance."""
    if source_local_index < 1:
        raise ValueError("source_local_index must start at one")
    return "-".join((
        "PC",
        _token(research_run_id, limit=25),
        _source_token(source_id, source_revision_id),
        f"{source_local_index:03d}",
    ))
