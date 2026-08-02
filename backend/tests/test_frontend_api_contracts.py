from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import _status_value, app
from src.contracts.analysis import AnalysisRunStatus


def test_public_job_status_uses_plain_contract_value() -> None:
    assert _status_value(AnalysisRunStatus.COMPLETED) == "COMPLETED"
    assert _status_value("PARTIAL") == "PARTIAL"


def test_fake_provider_geocodes_synthetic_sample_without_credentials(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDER_MODE", "fake")
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    response = TestClient(app).post("/v1/locations/geocode", json={"address": "서울 강남구 테헤란로 152"})
    assert response.status_code == 200
    assert response.json()["geocode_status"] == "SUCCESS"
    assert response.json()["provider"] == "DETERMINISTIC_FIXTURE"
    assert response.json()["normalized_address"] == "서울특별시 강남구 테헤란로 152"
    assert response.json()["latitude"] == "37.500950"
    assert response.json()["longitude"] == "127.036510"


def test_fake_provider_geocode_fails_closed_for_unknown_address(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_PROVIDER_MODE", "fake")
    response = TestClient(app).post("/v1/locations/geocode", json={"address": "서울특별시 알수없구 데모로 1"})
    assert response.status_code == 200
    assert response.json()["geocode_status"] == "NOT_FOUND"
    assert response.json()["latitude"] is None
    assert response.json()["longitude"] is None


def test_frontend_endpoints_have_named_response_models() -> None:
    schemas = app.openapi()["components"]["schemas"]
    for schema in ("AnalysisStatusResponse", "WhatIfResponse", "EventEvidenceResponse", "CandidateEvidenceResponse", "PolicyDetailResponse", "GeocodeResponse"):
        assert schema in schemas


def test_candidate_evidence_endpoint_is_in_the_public_contract() -> None:
    path = app.openapi()["paths"]["/v1/event-candidates/{candidate_id}/evidence"]["get"]
    schema = path["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/CandidateEvidenceResponse")

def test_policy_contract_exposes_all_visibility_groups() -> None:
    properties = app.openapi()["components"]["schemas"]["PolicyResultBundle"]["properties"]
    assert {"extracted_candidates", "eligible_recommendations", "reference_only_materials"} <= set(properties)
    stage_properties = app.openapi()["components"]["schemas"]["PolicyStageCounts"]["properties"]
    assert "reference_only_materials" in stage_properties
