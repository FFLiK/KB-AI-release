from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError

from src.contracts.event_candidate import EventType,ExtractedEventCandidate
from src.extraction.model_router import ModelRouter,RoutingContext
from src.normalization.amount_normalizer import normalize_amount,normalize_percentage
from src.normalization.date_normalizer import normalize_date
from src.registries.event_registry import EventRegistry,RegistryValidationError
from src.providers.extraction.schema_utils import ATTRIBUTE_KEYS,to_strict_provider_schema
from src.signals.evidence_score import calculate_evidence_score
from tests.research_fixtures import candidate,research_request


def test_every_enum_has_registry_entry_and_schema_is_strict():
    registry=EventRegistry()
    assert {x.value for x in EventType}==set(registry.events)
    schema=ExtractedEventCandidate.model_json_schema()
    assert schema["additionalProperties"] is False
    payload=candidate().model_dump(); payload["event_type"]="MADE_UP_EVENT"
    with pytest.raises(ValidationError): ExtractedEventCandidate.model_validate(payload)


def test_registry_enforces_required_attributes_and_mechanism():
    registry=EventRegistry(); item=candidate(); item.attributes={}
    with pytest.raises(RegistryValidationError) as exc: registry.validate_candidate(item)
    assert "MISSING_REQUIRED_FIELD" in exc.value.codes
    item=candidate(); item.impacts[0].mechanism="INVENTED"
    with pytest.raises(RegistryValidationError) as exc: registry.validate_candidate(item)
    assert "MECHANISM_NOT_SUPPORTED" in exc.value.codes


def test_research_request_window_is_strict():
    payload=research_request().model_dump(); payload["forecast_start"]=date(2026,10,1)
    with pytest.raises(ValidationError): type(research_request()).model_validate(payload)


def test_model_router_is_deterministic():
    router=ModelRouter()
    assert router.route_search(RoutingContext(official_results=0))=="HIGH"
    assert router.route_search(RoutingContext())=="MEDIUM"
    assert router.route_extraction(RoutingContext())=="LOW"
    assert router.route_extraction(RoutingContext(has_relative_dates=True))=="MEDIUM"
    assert router.route_extraction(RoutingContext(conflicting_official_sources=True))=="HIGH"


def test_korean_date_amount_and_percentage_normalization():
    parsed,rule=normalize_date("2026\ub144 8\uc6d4 1\uc77c",date(2026,7,1))
    assert parsed==date(2026,8,1) and rule=="KO_DATE_ABSOLUTE_V1"
    amount,currency,_=normalize_amount("1.5\uc5b5\uc6d0")
    assert amount==Decimal("150000000") and currency=="KRW"
    ratio,unit,_=normalize_percentage("2%p")
    assert ratio==Decimal("0.02") and unit=="PERCENTAGE_POINT"


def test_provider_schema_requires_all_properties_and_finite_attributes():
    schema=to_strict_provider_schema(ExtractedEventCandidate.model_json_schema())
    assert set(schema["properties"]["attributes"]["properties"])==set(ATTRIBUTE_KEYS)

    def assert_strict(node):
        if isinstance(node,dict):
            properties=node.get("properties")
            if isinstance(properties,dict):
                assert node.get("additionalProperties") is False
                assert set(node.get("required",[]))==set(properties)
            for value in node.values():
                assert_strict(value)
        elif isinstance(node,list):
            for value in node:
                assert_strict(value)
    assert_strict(schema)


def test_source_tier_scores_cover_persisted_source_types():
    assert calculate_evidence_score("OFFICIAL_PRIMARY")==1.0
    assert calculate_evidence_score("MAJOR_NEWS")==0.4
