"""Fail when repository files contain high-confidence credential material."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


PATTERNS = (
    re.compile("sk-" + r"proj-[A-Za-z0-9_-]{20,}"),
    re.compile("AI" + r"za[0-9A-Za-z_-]{30,}"),
    re.compile("AK" + r"IA[0-9A-Z]{16}"),
    re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
EXCLUDED = {".env.example"}


def repository_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
    ).stdout
    return [Path(value.decode("utf-8")) for value in output.split(b"\0") if value]


def main() -> None:
    findings: list[tuple[Path, int]] = []
    files = repository_files()
    for path in files:
        if path.as_posix() in EXCLUDED or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in PATTERNS):
                findings.append((path, line_number))
    if findings:
        locations = ", ".join(f"{path}:{line}" for path, line in findings)
        raise SystemExit(f"high-confidence secret material found at: {locations}")
    print(f"secret scan passed for {len(files)} repository files")


if __name__ == "__main__":
    main()
