import logging

from src.config.credential_validation import (
    credential_status,
    get_credential,
    validate_environment_keys,
)
from src.config.settings import Settings
from src.ingestion.official_api.map_api import MapApiAdapter


def test_credential_status_returns_only_safe_labels() -> None:
    values = {
        "MISSING": None,
        "EMPTY": "  ",
        "YOUR_STYLE": "YOUR_NAVER_CLIENT_ID_HERE",
        "CHANGE_ME": "CHANGE_ME",
        "ANGLE": "<secret>",
        "PLACEHOLDER": "placeholder",
        "REAL": "configured-test-value",
    }

    assert validate_environment_keys(values, values) == {
        "MISSING": "UNSET",
        "EMPTY": "UNSET",
        "YOUR_STYLE": "PLACEHOLDER",
        "CHANGE_ME": "PLACEHOLDER",
        "ANGLE": "PLACEHOLDER",
        "PLACEHOLDER": "PLACEHOLDER",
        "REAL": "SET",
    }
    assert set(validate_environment_keys(values, values).values()) == {
        "SET",
        "UNSET",
        "PLACEHOLDER",
    }


def test_placeholder_credentials_are_never_returned() -> None:
    environ = {
        "A": "YOUR_API_KEY_HERE",
        "B": "CHANGE_ME",
        "C": "<API_KEY>",
        "D": "PLACEHOLDER",
        "E": "usable-test-value",
    }

    assert all(get_credential(key, environ) is None for key in ("A", "B", "C", "D"))
    assert get_credential("E", environ) == "usable-test-value"
    assert credential_status(get_credential("A", environ)) == "UNSET"


def test_settings_reject_placeholder_llm_credentials(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "<OPENAI_API_KEY>")

    settings = Settings()

    assert settings.gemini_api_key is None
    assert settings.openai_api_key is None


def test_placeholder_geocoding_credentials_do_not_request_or_log_values(
    monkeypatch,
    caplog,
) -> None:
    placeholders = {
        "KAKAO_REST_API_KEY": "YOUR_KAKAO_REST_API_KEY_HERE",
        "NAVER_CLIENT_ID": "CHANGE_ME",
        "NAVER_CLIENT_SECRET": "<NAVER_SECRET>",
    }
    for key, value in placeholders.items():
        monkeypatch.setenv(key, value)

    def unexpected_request(*args, **kwargs):
        del args, kwargs
        raise AssertionError("placeholder credential triggered a request")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_request)
    caplog.set_level(logging.DEBUG)

    latitude, longitude, metadata = MapApiAdapter().geocode_address(
        "서울특별시 강남구 테헤란로 123"
    )

    assert latitude is None
    assert longitude is None
    assert metadata["geocode_status"] == "NOT_CONFIGURED"
    assert all(value not in caplog.text for value in placeholders.values())
