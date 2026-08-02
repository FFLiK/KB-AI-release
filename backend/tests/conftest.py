import asyncio
import os
import socket
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

_EXTERNAL_CREDENTIAL_KEYS = (
    "ECOS_API_KEY",
    "KOSIS_API_KEY",
    "DATA_GO_KR_API_KEY",
    "CUSTOMS_API_KEY",
    "PUBLIC_DATA_API_KEY",
    "KAKAO_REST_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
)

# This executes before test modules are imported, so application modules cannot
# repopulate provider credentials from the repository .env during collection.
os.environ["KB_AI_SKIP_DOTENV"] = "1"
for _credential_key in _EXTERNAL_CREDENTIAL_KEYS:
    os.environ.pop(_credential_key, None)


@pytest.fixture(autouse=True)
def isolate_external_providers(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep every non-live test credential-free and unable to open a network socket."""
    if request.node.get_closest_marker("live") is not None:
        monkeypatch.delenv("KB_AI_SKIP_DOTENV", raising=False)
        load_dotenv(override=True)
        return

    for key in _EXTERNAL_CREDENTIAL_KEYS:
        monkeypatch.delenv(key, raising=False)

    def blocked_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("External network access is forbidden in non-live tests")

    async def blocked_async_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("External network access is forbidden in non-live tests")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(asyncio.BaseEventLoop, "create_connection", blocked_async_network)


@pytest.fixture
def tmp_path() -> Path:
    """Workspace-local temp path for restricted Windows runners."""
    path = Path("data/test-runtime") / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path
