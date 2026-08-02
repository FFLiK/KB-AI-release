"""Bank of Korea decision-content checks used before monetary-policy extraction."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from src.contracts.source_document import SourceDocument


_RATE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*%")
_DATE = re.compile(
    r"(?:20\d{2}[./-]\s*\d{1,2}[./-]\s*\d{1,2}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+20\d{2}|"
    r"20\d{2}\ub144\s*\d{1,2}\uc6d4\s*\d{1,2}\uc77c)",
    re.IGNORECASE,
)
# Keep Korean tokens ASCII-escaped so Windows patch pipelines cannot corrupt them.
_BASE_RATE = re.compile(
    r"\b(?:base|policy)\s+rate\b|\uae30\uc900\s*\uae08\ub9ac", re.IGNORECASE,
)
_DECISION_CONTEXT = re.compile(
    r"\b(?:decided|decision|monetary\s+policy\s+board)\b|"
    r"\uae08\uc735\s*\ud1b5\ud654\s*\uc704\uc6d0\ud68c|\uacb0\uc815|"
    r"\uc6b4\uc6a9\ud558\uae30\ub85c|\ud1b5\ud654\s*\uc815\ucc45\s*\ubc29\ud5a5",
    re.IGNORECASE,
)
_HOLD = re.compile(
    r"\b(?:hold|held|maintain|maintained|keep|kept|unchanged)\b|"
    r"(?:\ub3d9\uacb0|\uc720\uc9c0|\ud604\s*\uc218\uc900)", re.IGNORECASE,
)
_INCREASE = re.compile(
    r"\b(?:raise|raised|increase|increased|hike|hiked)\b|(?:\uc778\uc0c1|\uc0c1\ud5a5)", re.IGNORECASE,
)
_DECREASE = re.compile(
    r"\b(?:lower|lowered|decrease|decreased|cut)\b|(?:\uc778\ud558|\ud558\ud5a5)", re.IGNORECASE,
)
_ENGLISH_CHANGE = re.compile(
    r"\bfrom\s+(?P<previous>\d+(?:\.\d+)?)\s*%\s+to\s+(?P<new>\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_CONNECTED_RATE_PATTERNS = (
    re.compile(
        r"(?:base|policy)\s+rate.{0,45}?(?:at|of|to)\s*(?P<rate>\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:hold|held|maintain|maintained|keep|kept).{0,45}?"
        r"(?:base|policy)\s+rate.{0,35}?(?P<rate>\d+(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    ),
)
_KOREAN_CHANGE = re.compile(
    r"(?P<previous>\d+(?:\.\d+)?)\s*%\s*(?:\uc5d0\uc11c|\ub85c\ubd80\ud130)\s*"
    r"(?P<new>\d+(?:\.\d+)?)\s*%\s*\ub85c", re.IGNORECASE,
)
_KOREAN_CONNECTED_RATE = re.compile(
    r"\uae30\uc900\s*\uae08\ub9ac.{0,55}?(?P<rate>\d+(?:\.\d+)?)\s*%"
    r".{0,30}?(?:\uc720\uc9c0|\ub3d9\uacb0|\uc778\uc0c1|\uc778\ud558)", re.IGNORECASE,
)
_CONNECTED_RATE_PATTERNS = (*_CONNECTED_RATE_PATTERNS, _KOREAN_CONNECTED_RATE)


@dataclass(frozen=True)
class BOKDecisionFacts:
    decision_type: str
    decision_date: str
    current_rate_percent: str
    previous_rate_percent: str | None = None
    new_rate_percent: str | None = None
    rate_selection_method: str = "DECISION_CLAUSE_ANCHORED"
    evidence_text: str = ""
    evidence_start_offset: int = 0
    evidence_end_offset: int = 0


@dataclass(frozen=True)
class BOKContentAssessment:
    usable: bool
    reason_codes: list[str] = field(default_factory=list)
    facts: BOKDecisionFacts | None = None


@dataclass(frozen=True)
class _DecisionCandidate:
    decision_type: str
    current_rate: str
    previous_rate: str | None
    new_rate: str | None
    start: int
    end: int
    evidence: str


def normalize_bok_official_text(value: str) -> str:
    """Normalize PDF line artifacts without inventing decision facts."""
    text = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    text = re.sub(r"(?<=\d)\s*[.]\s*(?=\d)", ".", text)
    text = re.sub(r"(?<=\d)\s+(?=\d|%)", "", text)
    text = re.sub(r"(?<=\d)\s*%", "%", text)
    return re.sub(r"\s+", " ", text).strip()


def _clause_spans(text: str) -> list[tuple[int, int]]:
    """Return bounded raw-text clauses while preserving evidence offsets."""
    boundaries = {0, len(text)}
    for match in re.finditer(r"[\u25a1\u25a0\u25c6](?=\s*)", text):
        boundaries.add(match.start())
    for match in re.finditer(r"[.!?](?=\s|$)", text):
        if match.group(0) == ".":
            left = text[:match.start()].rstrip()
            right = text[match.end():].lstrip()
            if (
                left and right
                and left[-1].isdigit() and right[0].isdigit()
            ):
                continue
        boundaries.add(match.end())
    ordered = sorted(boundaries)
    spans: list[tuple[int, int]] = []
    for start, end in zip(ordered, ordered[1:]):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            spans.append((start, end))
    return spans


def _decision_type(clause: str) -> str | None:
    if not (_BASE_RATE.search(clause) and _DECISION_CONTEXT.search(clause)):
        return None
    matches = [
        name for name, pattern in (
            ("HOLD", _HOLD), ("INCREASE", _INCREASE), ("DECREASE", _DECREASE)
        )
        if pattern.search(clause)
    ]
    return matches[0] if len(matches) == 1 else None


def _hold_rate(clause: str) -> tuple[str | None, str | None]:
    rates = {match.group(1) for match in _RATE.finditer(clause)}
    if not rates:
        return None, "BOK_CURRENT_RATE_MISSING"
    if len(rates) > 1:
        return None, "BOK_CURRENT_RATE_AMBIGUOUS"
    connected = {
        match.group("rate")
        for pattern in _CONNECTED_RATE_PATTERNS
        for match in pattern.finditer(clause)
    }
    if len(connected) == 1:
        return next(iter(connected)), None
    if len(connected) > 1:
        return None, "BOK_CURRENT_RATE_AMBIGUOUS"
    return next(iter(rates)), None


def _change_rates(clause: str) -> tuple[tuple[str, str] | None, str | None]:
    relationships = {
        (match.group("previous"), match.group("new"))
        for pattern in (_ENGLISH_CHANGE, _KOREAN_CHANGE)
        for match in pattern.finditer(clause)
    }
    if len(relationships) == 1:
        return next(iter(relationships)), None
    if len(relationships) > 1:
        return None, "BOK_RATE_CHANGE_VALUES_AMBIGUOUS"
    rates = {match.group(1) for match in _RATE.finditer(clause)}
    if len(rates) < 2:
        return None, "BOK_RATE_CHANGE_VALUES_INCOMPLETE"
    return None, "BOK_RATE_CHANGE_VALUES_AMBIGUOUS"


def parse_bok_decision(
    document: SourceDocument,
    *,
    official_rate_percent: Decimal | str | None = None,
) -> BOKContentAssessment:
    """Extract only rates explicitly connected to a monetary-policy decision."""
    raw = document.body_text
    text = normalize_bok_official_text(f"{document.title}\n{raw}")
    date_matches = list(_DATE.finditer(text))
    reasons: list[str] = []
    if not date_matches:
        reasons.append("BOK_DECISION_DATE_MISSING")

    candidates: list[_DecisionCandidate] = []
    candidate_failures: list[str] = []
    saw_decision_language = False
    for start, end in _clause_spans(raw):
        evidence = raw[start:end]
        clause = normalize_bok_official_text(evidence)
        if not (_BASE_RATE.search(clause) and _DECISION_CONTEXT.search(clause)):
            continue
        saw_decision_language = True
        decision_type = _decision_type(clause)
        if decision_type is None:
            continue
        if decision_type == "HOLD":
            current, failure = _hold_rate(clause)
            if failure:
                candidate_failures.append(failure)
                continue
            assert current is not None
            candidates.append(_DecisionCandidate(
                decision_type, current, None, None, start, end, evidence,
            ))
            continue
        relationship, failure = _change_rates(clause)
        if failure:
            candidate_failures.append(failure)
            continue
        assert relationship is not None
        previous, new = relationship
        candidates.append(_DecisionCandidate(
            decision_type, new, previous, new, start, end, evidence,
        ))

    if not saw_decision_language:
        reasons.append("BOK_DECISION_LANGUAGE_MISSING")
    if not candidates:
        reasons.extend(candidate_failures or ["BOK_CURRENT_RATE_MISSING"])
    identities = {
        (item.decision_type, item.current_rate, item.previous_rate, item.new_rate)
        for item in candidates
    }
    if len(identities) > 1:
        change = any(item.decision_type != "HOLD" for item in candidates)
        reasons.append(
            "BOK_RATE_CHANGE_VALUES_AMBIGUOUS" if change
            else "BOK_CURRENT_RATE_AMBIGUOUS"
        )
    if reasons:
        return BOKContentAssessment(
            usable=False, reason_codes=list(dict.fromkeys(reasons))
        )

    selected = min(candidates, key=lambda item: (item.start, item.end))
    facts = BOKDecisionFacts(
        decision_type=selected.decision_type,
        decision_date=date_matches[0].group(0),
        current_rate_percent=selected.current_rate,
        previous_rate_percent=selected.previous_rate,
        new_rate_percent=selected.new_rate,
        evidence_text=selected.evidence,
        evidence_start_offset=selected.start,
        evidence_end_offset=selected.end,
    )
    if official_rate_percent is not None:
        try:
            official = Decimal(str(official_rate_percent))
            selected_rate = Decimal(facts.current_rate_percent)
        except InvalidOperation:
            return BOKContentAssessment(
                usable=False, reason_codes=["BOK_RATE_OFFICIAL_DATA_CONFLICT"]
            )
        if official != selected_rate:
            return BOKContentAssessment(
                usable=False,
                reason_codes=["BOK_RATE_OFFICIAL_DATA_CONFLICT"],
                facts=facts,
            )
    return BOKContentAssessment(usable=True, facts=facts)


def is_bok_document(document: SourceDocument) -> bool:
    host = (urlsplit(document.canonical_url).hostname or "").lower()
    return host == "bok.or.kr" or host.endswith(".bok.or.kr")


def assess_bok_monetary_policy_content(
    document: SourceDocument,
    *,
    official_rate_percent: Decimal | str | None = None,
) -> BOKContentAssessment:
    return parse_bok_decision(document, official_rate_percent=official_rate_percent)


def should_recover_bok_attachment(document: SourceDocument) -> bool:
    return is_bok_document(document) and bool(document.attachment_urls) and not (
        assess_bok_monetary_policy_content(document).usable
    )
