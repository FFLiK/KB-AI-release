from __future__ import annotations

from datetime import date
import re

from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.source_document import AccessStatus, SourceDocument, SourceType
from src.validation.policy_identity import (
    policies_semantically_equivalent,
    material_policy_conflicts,
    policy_program_years,
    semantic_policy_merge_fingerprint,
)
from src.validation.policy_semantics import assess_policy_semantics


def validate_policy_candidate(
    policy: PolicyCandidate,
    documents: dict[str, SourceDocument],
    as_of_date: date,
) -> PolicyCandidate:
    """Bind policy evidence to stored revisions and return actionable failure codes."""
    codes: list[str] = []
    notes: list[str] = list(policy.validation_notes)
    related = {source_id: documents[source_id] for source_id in policy.source_ids if source_id in documents}
    if not related:
        codes.append("POLICY_SOURCE_MISSING")
    if set(related) != set(policy.source_ids):
        codes.append("POLICY_SOURCE_SET_MISMATCH")
    for document in related.values():
        if document.access_status != AccessStatus.OK:
            codes.append("POLICY_SOURCE_UNAVAILABLE")
        if document.security_flags:
            codes.append("POLICY_SOURCE_SECURITY_REJECTED")
        if document.source_type == SourceType.OTHER:
            codes.append("POLICY_SOURCE_UNTRUSTED")
    for evidence in policy.evidence:
        document = related.get(evidence.source_id)
        if not document:
            codes.append("POLICY_EVIDENCE_SOURCE_MISSING")
            continue
        body = document.body_text
        quote = evidence.quote
        unique_offset = body.find(quote)
        quote_is_unique = bool(quote) and unique_offset >= 0 and body.find(quote, unique_offset + 1) < 0
        if evidence.source_revision_id != document.revision_id:
            if quote_is_unique:
                evidence.source_revision_id = document.revision_id
                notes.append("POLICY_REVISION_REBOUND_TO_STORED_SOURCE")
            else:
                codes.append("POLICY_REVISION_MISMATCH")
        offset_matches = (
            0 <= evidence.start_offset < evidence.end_offset <= len(body)
            and body[evidence.start_offset:evidence.end_offset] == quote
        )
        if not offset_matches:
            if quote_is_unique:
                evidence.start_offset = unique_offset
                evidence.end_offset = unique_offset + len(quote)
                notes.append("POLICY_EVIDENCE_OFFSET_REPAIRED")
            elif unique_offset < 0:
                codes.append("POLICY_QUOTE_NOT_FOUND")
            else:
                codes.append("POLICY_OFFSET_AMBIGUOUS")
    semantic = assess_policy_semantics(policy, as_of_date)
    semantic_codes = semantic.failure_codes
    notes.extend(
        "POLICY_NUMERIC_NORMALIZED:"
        f"{item.field_path}={item.normalized_value} {item.normalized_unit}"
        for item in semantic.numeric_comparisons
        if item.matched
    )
    fallback_used = "POLICY_DETERMINISTIC_FALLBACK_USED" in policy.validation_notes
    if policy.notice_kind == "TERMINATION" or semantic.explicitly_closed or (
        policy.application_end is not None and policy.application_end < as_of_date
    ):
        policy.application_status = "CLOSED"
    elif fallback_used:
        policy.application_status = "STATUS_UNCONFIRMED"
    elif policy.budget_status.upper() in {"EXHAUSTED", "BUDGET_EXHAUSTED", "CLOSED"}:
        policy.application_status = "BUDGET_EXHAUSTED"
    elif policy.application_start is not None and policy.application_start > as_of_date:
        policy.application_status = "SCHEDULED"
    elif (
        policy.application_start is not None
        and policy.application_end is not None
        and policy.application_start <= as_of_date <= policy.application_end
    ):
        policy.application_status = "OPEN"
    else:
        policy.application_status = "STATUS_UNCONFIRMED"
    status_failure_codes = {
        "CLOSED": "POLICY_CLOSED",
        "BUDGET_EXHAUSTED": "POLICY_BUDGET_EXHAUSTED",
        "SCHEDULED": "POLICY_NOT_YET_OPEN",
        "STATUS_UNCONFIRMED": "POLICY_STATUS_UNCONFIRMED",
    }
    policy.recommendation_failure_codes = sorted(set([
        *([status_failure_codes[policy.application_status]]
          if policy.application_status in status_failure_codes else []),
        *(["POLICY_BUDGET_UNKNOWN"]
          if policy.budget_status.upper() in {"UNKNOWN", "BUDGET_UNKNOWN"} else []),
    ]))
    policy.validation_failure_codes = sorted(set([*codes, *semantic_codes]))
    policy.validation_notes = sorted(set(notes))
    if codes:
        policy.validation_status = "REJECTED"
    elif policy.notice_kind == "TERMINATION" or semantic.explicitly_closed or (
        policy.application_end is not None and policy.application_end < as_of_date
    ):
        policy.validation_status = "CLOSED"
    elif semantic_codes:
        policy.validation_status = "PARTIALLY_VALIDATED"
    else:
        policy.validation_status = "VALIDATED"
    return policy


def _ordered_unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _first_informative(values, *, unknown_values=()):
    ignored = {None, "", *unknown_values}
    return next((value for value in values if value not in ignored), None)


def _merge_consistent_policy_fields(
    primary: PolicyCandidate,
    policies: list[PolicyCandidate],
) -> dict[str, object]:
    """Preserve the most specific non-conflicting value supplied by any source."""
    ordered = sorted(policies, key=lambda item: item.policy_candidate_id)
    interest = primary.interest_terms.model_copy(update={
        "annual_rate_percent": _first_informative(
            item.interest_terms.annual_rate_percent for item in ordered
        ),
        "rate_discount_percentage_points": _first_informative(
            item.interest_terms.rate_discount_percentage_points for item in ordered
        ),
    })
    guarantee = primary.guarantee_terms.model_copy(update={
        "coverage_ratio": _first_informative(
            item.guarantee_terms.coverage_ratio for item in ordered
        ),
        "guarantee_fee_percent": _first_informative(
            item.guarantee_terms.guarantee_fee_percent for item in ordered
        ),
        "collateral_required": _first_informative(
            item.guarantee_terms.collateral_required for item in ordered
        ),
    })
    repayment = primary.repayment_terms.model_copy(update={
        "principal_grace_months": _first_informative(
            item.repayment_terms.principal_grace_months for item in ordered
        ),
        "maturity_months": _first_informative(
            item.repayment_terms.maturity_months for item in ordered
        ),
        "repayment_method": _first_informative(
            item.repayment_terms.repayment_method for item in ordered
        ),
    })
    return {
        "purpose": _ordered_unique(value for item in ordered for value in item.purpose),
        "region_codes": _ordered_unique(
            value for item in ordered for value in item.region_codes
        ),
        "industry_inclusions_raw": _ordered_unique(
            value for item in ordered for value in item.industry_inclusions_raw
        ),
        "industry_exclusions_raw": _ordered_unique(
            value for item in ordered for value in item.industry_exclusions_raw
        ),
        "limit_krw": _first_informative(item.limit_krw for item in ordered),
        "interest_terms": interest,
        "guarantee_terms": guarantee,
        "repayment_terms": repayment,
        "application_start": _first_informative(
            item.application_start for item in ordered
        ),
        "application_end": _first_informative(
            item.application_end for item in ordered
        ),
        "budget_status": _first_informative(
            (item.budget_status for item in ordered),
            unknown_values=("UNKNOWN", "BUDGET_UNKNOWN"),
        ) or primary.budget_status,
        "application_status": _first_informative(
            (item.application_status for item in ordered),
            unknown_values=("UNKNOWN", "STATUS_UNCONFIRMED"),
        ) or primary.application_status,
        "eligibility_conditions": _ordered_unique(
            value for item in ordered for value in item.eligibility_conditions
        ),
    }


def _canonical_policy_primary(
    policies: list[PolicyCandidate],
    documents: dict[str, SourceDocument] | None,
) -> PolicyCandidate:
    """Choose the most specific, strongest official representation deterministically."""
    docs = documents or {}

    def strength(policy: PolicyCandidate) -> tuple[int, int, int, float, str]:
        related = [docs[source_id] for source_id in policy.source_ids if source_id in docs]
        official_sources = sum(
            1 for document in related
            if document.source_type in {
                SourceType.OFFICIAL_PRIMARY,
                SourceType.OFFICIAL_SECONDARY,
                SourceType.OFFICIAL_LOCAL_GOV,
            }
        )
        latest_published = max(
            (document.published_at.timestamp() for document in related if document.published_at),
            default=0.0,
        )
        year_specific_label = bool(re.search(r"20\d{2}", policy.name)) or any(
            bool(re.search(r"20\d{2}", document.title))
            for document in related
        )
        return (
            int(year_specific_label),
            official_sources,
            len(policy.evidence),
            latest_published,
            policy.policy_candidate_id,
        )

    return sorted(
        policies,
        key=lambda item: (
            -strength(item)[0], -strength(item)[1], -strength(item)[2],
            -strength(item)[3], strength(item)[4],
        ),
    )[0]
class PolicyReconciler:
    """Links correction/termination notices without letting an LLM decide eligibility."""
    def reconcile(
        self,
        policies: list[PolicyCandidate],
        documents: dict[str, SourceDocument] | None = None,
    ) -> list[PolicyCandidate]:
        """Merge duplicate original notices, while retaining correction lineage."""
        groups: list[list[PolicyCandidate]] = []
        for policy in sorted(policies, key=lambda item: item.policy_candidate_id):
            compatible = next((
                group for group in groups
                if all(
                    policies_semantically_equivalent(policy, item, documents)
                    for item in group
                )
            ), None)
            if compatible is None:
                groups.append([policy])
            else:
                compatible.append(policy)
        result: list[PolicyCandidate] = []
        revision_notice_kinds = {"CORRECTION", "TERMINATION"}
        for group in groups:
            ordered = sorted(
                group,
                key=lambda policy: (
                    policy.application_start or policy.application_end or date.min,
                    policy.policy_candidate_id,
                ),
            )
            originals = [
                policy for policy in ordered
                if policy.notice_kind not in revision_notice_kinds
            ]
            previous: PolicyCandidate | None = None
            if originals:
                primary = _canonical_policy_primary(originals, documents)
                merge_fingerprint = semantic_policy_merge_fingerprint(originals, documents)
                merge_group_id = "PMG-" + merge_fingerprint[:20].upper()
                merged_candidate_ids = sorted({
                    policy.extractor_policy_candidate_id or policy.policy_candidate_id
                    for policy in originals
                })
                source_ids = sorted({source_id for policy in originals for source_id in policy.source_ids})
                evidence_by_source = {
                    (
                        evidence.source_id,
                        evidence.source_revision_id,
                        tuple(evidence.field_paths),
                        evidence.quote,
                    ): evidence
                    for policy in originals
                    for evidence in policy.evidence
                }
                source_validation_details = [
                    {
                        "policy_candidate_id": policy.policy_candidate_id,
                        "extractor_policy_candidate_id": policy.extractor_policy_candidate_id,
                        "source_ids": sorted(policy.source_ids),
                        "status": policy.validation_status,
                        "failure_codes": sorted(policy.validation_failure_codes),
                        "validation_notes": sorted(policy.validation_notes),
                    }
                    for policy in sorted(
                        originals,
                        key=lambda item: (
                            tuple(sorted(item.source_ids)), item.policy_candidate_id
                        ),
                    )
                ]
                signatures = {
                    (
                        policy.validation_status,
                        tuple(sorted(policy.validation_failure_codes)),
                    )
                    for policy in originals
                }
                reconciled_status = primary.validation_status
                failure_codes = sorted({
                    code for policy in originals
                    for code in policy.validation_failure_codes
                })
                recommendation_codes = sorted({
                    code for policy in originals
                    for code in policy.recommendation_failure_codes
                })
                if len(signatures) > 1:
                    statuses = {policy.validation_status for policy in originals}
                    reconciled_status = (
                        "PARTIALLY_VALIDATED"
                        if statuses <= {"VALIDATED", "PARTIALLY_VALIDATED"}
                        else "CONFLICTED"
                    )
                    failure_codes = sorted({*failure_codes, "SOURCE_CONFLICT"})
                    recommendation_codes = sorted({
                        *recommendation_codes, "SOURCE_CONFLICT"
                    })
                primary = primary.model_copy(update={
                    **_merge_consistent_policy_fields(primary, originals),
                    "policy_candidate_id": (
                        "POL-" + merge_fingerprint[:24].upper()
                        if len(originals) > 1 else primary.policy_candidate_id
                    ),
                    "identity_fingerprint": merge_fingerprint if len(originals) > 1 else primary.identity_fingerprint,
                    "policy_merge_group_id": merge_group_id if len(originals) > 1 else None,
                    "merged_policy_candidate_ids": merged_candidate_ids if len(originals) > 1 else [],
                    "source_ids": source_ids,
                    "evidence": list(evidence_by_source.values()),
                    "validation_status": reconciled_status,
                    "validation_failure_codes": failure_codes,
                    "recommendation_failure_codes": recommendation_codes,
                    "source_validation_details": source_validation_details,
                })
                result.append(primary)
                previous = primary
            for policy in ordered:
                if policy.notice_kind not in revision_notice_kinds:
                    continue
                if previous and policy.notice_kind in {"CORRECTION", "TERMINATION"}:
                    policy.supersedes_policy_candidate_id = previous.policy_candidate_id
                if policy.notice_kind == "TERMINATION" and not policy.validation_failure_codes:
                    policy.validation_status = "CLOSED"
                result.append(policy)
                previous = policy
        conflicts_by_source: dict[str, set[str]] = {}
        ordered_input = sorted(policies, key=lambda item: item.policy_candidate_id)
        for index, left in enumerate(ordered_input):
            for right in ordered_input[index + 1:]:
                conflicting_fields = material_policy_conflicts(left, right, documents)
                if not conflicting_fields:
                    continue
                for source_id in [*left.source_ids, *right.source_ids]:
                    conflicts_by_source.setdefault(source_id, set()).update(conflicting_fields)
        conflicted_result: list[PolicyCandidate] = []
        for policy in result:
            conflicting_fields = sorted({
                field_name for source_id in policy.source_ids
                for field_name in conflicts_by_source.get(source_id, set())
            })
            if not conflicting_fields:
                conflicted_result.append(policy)
                continue
            details = [
                *policy.source_validation_details,
                {
                    "source_ids": sorted(policy.source_ids),
                    "status": "CONFLICTED",
                    "failure_codes": ["SOURCE_CONFLICT"],
                    "conflicting_fields": conflicting_fields,
                },
            ]
            conflicted_result.append(policy.model_copy(update={
                "validation_status": "CONFLICTED",
                "validation_failure_codes": sorted({
                    *policy.validation_failure_codes, "SOURCE_CONFLICT",
                }),
                "recommendation_failure_codes": sorted({
                    *policy.recommendation_failure_codes, "SOURCE_CONFLICT",
                }),
                "source_validation_details": details,
            }))
        return sorted(conflicted_result, key=lambda policy: policy.policy_candidate_id)
