from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "frontend", ROOT / "src", ROOT / "tests", ROOT / "docs", ROOT / "README.md"]
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".py", ".ts", ".tsx", ".yml", ".yaml"}
SKIP_PARTS = {"dist", "node_modules", "playwright-report", "playwright-report-real", "test-results"}
MOJIBAKE_MARKERS = ("\ufffd", "\u00c3", "\u00c2", "\u00e2\u20ac")
QUESTION_PLACEHOLDER = re.compile(r"([\"'`])\?+\1|>\?+<")


def files_to_check() -> list[Path]:
    files: list[Path] = []
    for target in TARGETS:
        if target.is_file():
            files.append(target)
        elif target.exists():
            files.extend(
                path
                for path in target.rglob("*")
                if path.is_file()
                and path.suffix.lower() in TEXT_SUFFIXES
                and not any(part in SKIP_PARTS for part in path.parts)
            )
    return sorted(set(files))


def main() -> int:
    failures: list[str] = []
    files = files_to_check()
    for path in files:
        relative = path.relative_to(ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{relative}: invalid UTF-8: {exc}")
            continue
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                failures.append(f"{relative}: mojibake marker {marker.encode('unicode_escape').decode()}")
        for line_number, line in enumerate(text.splitlines(), 1):
            if QUESTION_PLACEHOLDER.search(line):
                failures.append(f"{relative}:{line_number}: question-mark placeholder")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"UTF-8 and placeholder scan passed for {len(files)} text files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
