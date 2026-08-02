from src.providers.extraction.prompts import build_prompt


def test_local_extraction_prompt_contains_domain_registry_constraints() -> None:
    prompt = build_prompt(
        "LOCAL",
        "stored source body",
        "SRC-TEST",
        "REV-TEST",
        research_run_id="RUN-TEST",
        model="test-model",
    )

    assert '"LOCAL_FESTIVAL"' in prompt
    assert '"family":"LOCAL_EVENT"' in prompt
    assert '"allowed_mechanisms":["LOCAL_FOOT_TRAFFIC_CHANGE"]' in prompt
    assert '"allowed_directions":{"REVENUE_DEMAND":["INCREASE"]}' in prompt
    assert '"BASE_RATE_INCREASE"' not in prompt
