from src.providers.extraction.prompts import build_prompt


def test_extraction_prompt_requires_validator_field_paths() -> None:
    prompt = build_prompt(
        "MACRO",
        "stored source body",
        "SRC-TEST",
        "REV-TEST",
        research_run_id="RUN-TEST",
    )

    assert "Evidence field_paths must name extracted fields, never body_text" in prompt
    assert "event_type" in prompt
    assert "temporal.start_raw" in prompt
    assert "impacts[i]" in prompt
