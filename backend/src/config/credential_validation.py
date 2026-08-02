"""Credential validation helpers that never expose credential values."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from typing import Literal

CredentialStatus = Literal["SET", "UNSET", "PLACEHOLDER"]

_PLACEHOLDER_VALUES = {
    "CHANGE_ME",
    "CHANGEME",
    "PLACEHOLDER",
    "REPLACE_ME",
    "REPLACEME",
    "TODO",
}
_ANGLE_BRACKET_PLACEHOLDER = re.compile(r"^<[^>]+>$")


def credential_status(value: str | None) -> CredentialStatus:
    """Return only a safe status label for a possible credential."""
    if value is None or not value.strip():
        return "UNSET"

    normalized = value.strip()
    upper = normalized.upper()
    if (
        upper.startswith("YOUR_")
        or upper in _PLACEHOLDER_VALUES
        or _ANGLE_BRACKET_PLACEHOLDER.fullmatch(normalized) is not None
    ):
        return "PLACEHOLDER"
    return "SET"


def get_credential(
    key: str,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Return a usable credential, or ``None`` for unset/placeholder values."""
    source = os.environ if environ is None else environ
    value = source.get(key)
    return value if credential_status(value) == "SET" else None


def validate_environment_keys(
    keys: Iterable[str],
    environ: Mapping[str, str] | None = None,
) -> dict[str, CredentialStatus]:
    """Return credential presence statuses without returning any values."""
    source = os.environ if environ is None else environ
    return {key: credential_status(source.get(key)) for key in keys}
