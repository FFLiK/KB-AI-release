from src.validation.reconciler import EventReconciler,assign_cause_groups
from src.validation.research_validator import ResearchEventValidator
from src.contracts.source_document import SourceType
from tests.research_fixtures import candidate,research_request,source_document


def test_grounded_candidate_is_accepted_with_rule_ids():
    doc=source_document(); outcome=ResearchEventValidator().validate(candidate(doc),{doc.source_id:doc},research_request())
    assert outcome.status=="ACCEPTED"
    assert outcome.event and outcome.event.evidence
    assert all(record.rule_id for record in outcome.event.normalization_records)


def test_outside_radius_is_rejected():
    doc=source_document(); far=candidate(doc,lat=35.0,lon=129.0)
    outcome=ResearchEventValidator().validate(far,{doc.source_id:doc},research_request())
    assert outcome.status=="REJECTED" and "OUTSIDE_SEARCH_RADIUS" in outcome.failure_codes


def test_offset_hallucination_is_not_accepted():
    doc=source_document(); item=candidate(doc); item.evidence[0].quote="not in source"
    outcome=ResearchEventValidator().validate(item,{doc.source_id:doc},research_request())
    assert outcome.status!="ACCEPTED" and "OFFSET_MISMATCH" in outcome.failure_codes


def test_prompt_injection_document_fails_closed():
    doc=source_document(security_flags=["PROMPT_INJECTION_PATTERN_1"])
    outcome=ResearchEventValidator().validate(candidate(doc),{doc.source_id:doc},research_request())
    assert outcome.status=="REJECTED" and "PROMPT_INJECTION_DETECTED" in outcome.failure_codes


def test_unknown_source_is_retained_as_reference_only():
    doc=source_document().model_copy(update={"source_type":SourceType.OTHER})
    outcome=ResearchEventValidator().validate(candidate(doc),{doc.source_id:doc},research_request())
    assert outcome.status=="REFERENCE_ONLY"
    assert "SOURCE_UNTRUSTED" in outcome.failure_codes


def test_duplicate_merge_preserves_sources_and_conflict_is_excluded():
    validator=ResearchEventValidator(); d1=source_document(source_id="SRC-1",revision_id="REV-1"); d2=source_document(source_id="SRC-2",revision_id="REV-2")
    e1=validator.validate(candidate(d1,"EVC-1"),{d1.source_id:d1},research_request()).event
    e2=validator.validate(candidate(d2,"EVC-2"),{d2.source_id:d2},research_request()).event
    accepted,excluded=EventReconciler().reconcile([e1,e2]); assert len(accepted)==1 and set(accepted[0].source_ids)=={"SRC-1","SRC-2"}
    e3=e2.model_copy(deep=True); e3.start_date=e3.start_date.replace(day=2); e3.fingerprint=e1.fingerprint
    accepted,excluded=EventReconciler().reconcile([e1,e3]); assert not accepted and any(e.validation_status=="CONFLICTED" for e in excluded)


def test_official_indicator_cause_group_disables_duplicate_news_signal():
    doc=source_document(); event=ResearchEventValidator().validate(candidate(doc),{doc.source_id:doc},research_request()).event
    event.impacts[0].axis="INGREDIENT_COST"
    grouped=assign_cause_groups([event],["FX_USD_KRW_SNAPSHOT"])
    assert grouped[0].signal_enabled is False and grouped[0].cause_group_id
    assert "official indicator" in grouped[0].signal_eligibility_reason.lower()


def test_independent_ingredient_supply_shock_is_not_suppressed_by_price_indicators():
    doc=source_document(); event=ResearchEventValidator().validate(candidate(doc),{doc.source_id:doc},research_request()).event
    event.event_type="INGREDIENT_SHORTAGE"
    event.event_family="INGREDIENT_SUPPLY"
    event.impacts[0].axis="INGREDIENT_COST"
    event.impacts[0].direction="INCREASE"
    event.impacts[0].mechanism="SUPPLY_DISRUPTION"
    grouped=assign_cause_groups(
        [event], ["USD_KRW", "IMPORT_PRICE_INDEX_USD"]
    )
    assert grouped[0].signal_enabled is True
    assert grouped[0].cause_group_id
