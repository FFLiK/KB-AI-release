from __future__ import annotations

import hashlib
from collections import defaultdict

from src.contracts.canonical_event import CanonicalEvent

TIER={"OFFICIAL_PRIMARY":5,"OFFICIAL_LOCAL_GOV":5,"OFFICIAL_SECONDARY":4,"FINANCIAL_INSTITUTION":4,"MAJOR_NEWS":2,"OTHER":0}


class EventReconciler:
    def reconcile(self,events: list[CanonicalEvent], *, as_of_date=None) -> tuple[list[CanonicalEvent],list[CanonicalEvent]]:
        groups=defaultdict(list)
        for event in sorted(events, key=lambda item: (item.fingerprint, item.event_id)): groups[event.fingerprint].append(event)
        accepted=[]; excluded=[]
        for fingerprint in sorted(groups):
            group = sorted(groups[fingerprint], key=lambda item: item.event_id)
            base=group[0].model_copy(deep=True)
            for other in group[1:]:
                same_bok_identity = base.actor_org_id == other.actor_org_id == "ORG-BOK" and base.attributes.get("official_indicator_id") == other.attributes.get("official_indicator_id") == "BASE_RATE"
                if not same_bok_identity and (base.start_date,base.end_date,base.location.normalized_address)!=(other.start_date,other.end_date,other.location.normalized_address):
                    left,right=TIER.get(base.source_tier,0),TIER.get(other.source_tier,0)
                    if left==right:
                        base.validation_status="CONFLICTED"; base.validation_failure_codes=["SOURCE_CONFLICT"]; base.signal_enabled=False
                        rejected=other.model_copy(deep=True); rejected.validation_status="CONFLICTED"; rejected.validation_failure_codes=["SOURCE_CONFLICT"]; rejected.signal_enabled=False
                        excluded.append(rejected)
                    elif right>left:
                        rejected=base.model_copy(deep=True); rejected.validation_status="REFERENCE_ONLY"; rejected.validation_failure_codes=["SOURCE_CONFLICT"]; rejected.signal_enabled=False
                        excluded.append(rejected); base=other.model_copy(deep=True)
                    else:
                        rejected=other.model_copy(deep=True); rejected.validation_status="REFERENCE_ONLY"; rejected.validation_failure_codes=["SOURCE_CONFLICT"]; rejected.signal_enabled=False
                        excluded.append(rejected)
                    continue
                base.candidate_ids=sorted(set(base.candidate_ids+other.candidate_ids))
                base.source_ids=sorted(set(base.source_ids+other.source_ids))
                base.source_revision_ids=sorted(set(base.source_revision_ids+other.source_revision_ids))
                evidence={x.evidence_id:x for x in base.evidence+other.evidence}; base.evidence=[evidence[key] for key in sorted(evidence)]
                if base.actor_org_id == "ORG-BOK" and base.attributes.get("official_indicator_id") == "BASE_RATE":
                    base.attributes = {**base.attributes, "merge_reason": "NORMALIZED_MONETARY_POLICY_IDENTITY_MATCH", "merged_candidate_ids": base.candidate_ids}
                base.title = min(base.title, other.title)
                duplicate=other.model_copy(deep=True); duplicate.validation_status="REFERENCE_ONLY"; duplicate.validation_failure_codes=["DUPLICATE_EVENT"]; duplicate.signal_enabled=False; excluded.append(duplicate)
            (accepted if base.validation_status=="ACCEPTED" else excluded).append(base)
        bok_events = sorted((event for event in accepted if event.actor_org_id == "ORG-BOK" and event.attributes.get("official_indicator_id") == "BASE_RATE"), key=lambda item: (item.start_date, item.event_id))
        effective_events = [event for event in bok_events if as_of_date is None or event.start_date <= as_of_date]
        current_bok_event = effective_events[-1] if effective_events else None
        for event in bok_events:
            if event is current_bok_event:
                event.attributes = {**event.attributes, "lifecycle_status": "CURRENT_OFFICIAL_DECISION"}
                continue
            later = next((item for item in bok_events if item.start_date > event.start_date), None)
            if later:
                from datetime import timedelta
                event.end_date = later.start_date - timedelta(days=1)
                event.attributes = {
                    **event.attributes,
                    "lifecycle_status": "SUPERSEDED_BY_LATER_DECISION",
                    "superseded_by_event_id": later.event_id,
                    "effective_through": event.end_date.isoformat(),
                }
                # Historical decisions remain auditable, but never emit a
                # parallel current financial signal.
                event.signal_enabled = False
                event.signal_eligibility_reason = "Superseded by a later Bank of Korea BASE_RATE decision."
            else:
                event.attributes = {**event.attributes, "lifecycle_status": "FUTURE_OFFICIAL_DECISION"}
                event.signal_enabled = False
                event.signal_eligibility_reason = "Decision is not effective as of the analysis date."
        return sorted(accepted, key=lambda item: item.event_id), sorted(excluded, key=lambda item: item.event_id)

def assign_cause_groups(events: list[CanonicalEvent],official_indicator_ids: list[str]) -> list[CanonicalEvent]:
    for event in events:
        axis=str(event.impacts[0].axis)
        if axis=="INTEREST_COST": key="INTEREST_RATE"
        elif axis=="INGREDIENT_COST": key="FX_IMPORT_INGREDIENT"
        else: key=event.event_id
        event.cause_group_id="CAUSE-"+hashlib.sha256(key.encode()).hexdigest()[:16].upper()
        mechanisms = {impact.mechanism for impact in event.impacts}
        independent_supply_shock = bool(
            mechanisms.intersection({"SUPPLY_DISRUPTION", "SUPPLY_RECOVERY"})
        )
        if ((key=="INTEREST_RATE" and any("RATE" in x for x in official_indicator_ids)) or
            (key=="FX_IMPORT_INGREDIENT" and not independent_supply_shock and
             any(token in x for x in official_indicator_ids for token in ("FX","IMPORT_PRICE")))):
            event.signal_enabled=False
            event.signal_eligibility_reason = (
                "An official indicator already represents this financial cause group."
            )
    return events
