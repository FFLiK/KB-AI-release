"""Deterministic temporal-relevance checks for display-only research findings."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from src.contracts.research import ResearchRequest
from src.contracts.source_document import SourceDocument


_PROPOSAL = re.compile(
    r"\b(?:proposal|proposed|consultation|public comment|draft rule)\b|"
    r"(?:\uc785\ubc95\uc608\uace0|\ud589\uc815\uc608\uace0|\uc758\uacac\s*\uc218\ub834|\uacf5\uace0\uc548|\uc81c\uc548)",
    re.IGNORECASE,
)
_FINAL_STATE = re.compile(
    r"\b(?:adopted|enacted|implemented|implementation notice|final rule|in force)\b|"
    r"(?:\ud655\uc815|\uacf5\ud3ec|\uc2dc\ud589\s*\uc911|\uc2dc\ud589\ud558\uae30\ub85c|\ucd5c\uc885\s*\uacb0\uc815)",
    re.IGNORECASE,
)
_SUPERSEDED = re.compile(
    r"\b(?:superseded|replaced|withdrawn|revoked)\b|"
    r"(?:\ud3d0\uae30|\ucca0\ud68c|\ub300\uccb4|\ud3d0\uc9c0|\uc774\s*\uacf5\uace0\ub294\s*\ud3d0\uc9c0)",
    re.IGNORECASE,
)
_ONGOING = re.compile(
    r"\b(?:remains? in (?:force|effect)|currently effective|continues? to apply|"
    r"until (?:funds? are )?exhausted|ongoing)\b|"
    r"(?:\ud604\ud589|\uc720\ud6a8|\uacc4\uc18d\s*\uc801\uc6a9|\uc2dc\ud589\s*\uc911|\uc608\uc0b0\s*\uc18c\uc9c4\s*\uc2dc\uae4c\uc9c0|\ub2e4\uc74c\s*\uacb0\uc815\s*\uc2dc\uae4c\uc9c0)",
    re.IGNORECASE,
)
_TIME_SENSITIVE = re.compile(
    r"\b(?:closure|closed|construction|event|festival|application period|"
    r"tariff|quota|restriction|consultation|public comment|proposal|temporary)\b|"
    r"(?:\ud1b5\uc81c|\uacf5\uc0ac|\ud589\uc0ac|\ucd95\uc81c|\uc2e0\uccad\s*\uae30\uac04|\uad00\uc138|\ud560\ub2f9\uad00\uc138|"
    r"\uc81c\ud55c|\uc758\uacac\s*\uc218\ub834|\uc608\uace0|\uc784\uc2dc)",
    re.IGNORECASE,
)
_EVENT_ENDED = re.compile(
    r"\b(?:ended|expired|closed on|through|until)\b|(?:\uc885\ub8cc|\ub9c8\uac10|\ub9cc\ub8cc|\uc885\ub8cc\uc77c)",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(?<!\d)(20\d{2})[./-](\d{1,2})[./-](\d{1,2})(?!\d)")
_KOREAN_DATE = re.compile(
    r"(?<!\d)(20\d{2})\s*\ub144\s*(\d{1,2})\s*\uc6d4\s*(\d{1,2})\s*\uc77c"
)
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


@dataclass(frozen=True)
class ReferenceFreshnessDecision:
    promotable: bool
    status: str
    reason_codes: list[str] = field(default_factory=list)


def _explicit_dates(text: str) -> list[date]:
    values: set[date] = set()
    for pattern in (_ISO_DATE, _KOREAN_DATE):
        for match in pattern.finditer(text):
            try:
                values.add(date(*(int(item) for item in match.groups())))
            except ValueError:
                continue
    return sorted(values)


def _latest_claim_boundary(text: str) -> date | None:
    dates = _explicit_dates(text)
    if dates:
        return dates[-1]
    years = [int(match.group(1)) for match in _YEAR.finditer(text)]
    return date(max(years), 12, 31) if years else None


def evaluate_reference_freshness(
    request: ResearchRequest,
    document: SourceDocument,
    *,
    reference_summary: str,
    evidence_text: str,
) -> ReferenceFreshnessDecision:
    """Reject stale time-sensitive material without using a blanket age cutoff."""
    text = " ".join((document.title, reference_summary, evidence_text, document.body_text))
    if _SUPERSEDED.search(text):
        return ReferenceFreshnessDecision(
            False, "SUPERSEDED", ["REFERENCE_SUPERSEDED"]
        )

    proposal = bool(_PROPOSAL.search(text))
    final_state = bool(_FINAL_STATE.search(text))
    ongoing = bool(_ONGOING.search(text))
    boundary = _latest_claim_boundary(text)

    if proposal and not final_state:
        codes = ["REFERENCE_IMPLEMENTATION_UNCONFIRMED"]
        if boundary is None or boundary < request.forecast_start:
            codes.insert(0, "REFERENCE_STALE_PROPOSAL")
        return ReferenceFreshnessDecision(False, "STALE_PROPOSAL", codes)

    if ongoing or final_state:
        return ReferenceFreshnessDecision(True, "CURRENT_CONFIRMED", [])

    if _TIME_SENSITIVE.search(text):
        if boundary is None:
            return ReferenceFreshnessDecision(
                False, "TEMPORAL_EVIDENCE_MISSING", ["REFERENCE_NO_ONGOING_RELEVANCE"]
            )
        if boundary < request.forecast_start:
            code = "REFERENCE_EXPIRED" if _EVENT_ENDED.search(text) else "REFERENCE_STALE"
            return ReferenceFreshnessDecision(
                False, "EXPIRED" if code == "REFERENCE_EXPIRED" else "STALE",
                [code, "REFERENCE_NO_ONGOING_RELEVANCE"],
            )

    return ReferenceFreshnessDecision(True, "CURRENT_OR_TIME_INVARIANT", [])
