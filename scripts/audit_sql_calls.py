"""Static audit helper for SQL execution calls.

Flags call sites where `.execute(...)` appears to receive a raw string literal
instead of `sqlalchemy.text(...)` / `sql_text(...)`.

Usage:
    python scripts/audit_sql_calls.py

Exit code:
    0 = no raw-literal execute() patterns found
    1 = one or more suspicious patterns found
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "app"

PATTERN = re.compile(r"\.execute\(\s*(?:f?\"|f?')")
ALLOW = (
    "cursor.execute(",
    "session.execute =",  # monkeypatch wrapper in models/db.py
)


def main() -> int:
    findings: list[tuple[str, int, str]] = []
    for path in SRC.rglob("*.py"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, start=1):
            if any(tok in line for tok in ALLOW):
                continue
            if PATTERN.search(line):
                findings.append((str(path.relative_to(ROOT)), idx, line.strip()))

    if findings:
        print("Raw SQL execute() literals detected:")
        for p, ln, text in findings:
            print(f"- {p}:{ln}: {text[:180]}")
        return 1

    print("No suspicious raw-literal execute() patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
