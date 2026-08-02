from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"system\s+prompt",
        r"developer\s+message",
        r"execute\s+(this\s+)?command",
        r"read\s+.*(?:api[_ -]?key|password|secret)",
        r"\uc774\uc804\s*\uc9c0\uc2dc.*\ubb34\uc2dc",
        r"\uc2dc\uc2a4\ud15c\s*\ud504\ub86c\ud504\ud2b8",
        r"\uba85\ub839(?:\uc5b4)?\s*\uc2e4\ud589",
    )
]


def assert_public_url(url: str) -> None:
    host = urlsplit(url).hostname
    if not host:
        raise ValueError("SOURCE_UNAVAILABLE: URL has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError("SOURCE_UNAVAILABLE: DNS lookup failed") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ValueError("BLOCKED_PRIVATE_NETWORK")


def detect_prompt_injection(text: str) -> list[str]:
    return [f"PROMPT_INJECTION_PATTERN_{index + 1}" for index, pattern in enumerate(INJECTION_PATTERNS) if pattern.search(text)]
