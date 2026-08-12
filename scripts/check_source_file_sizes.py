"""Fail when a new maintained source file exceeds 2,000 lines; warn above 1,000."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / "config/source_file_size_baseline.json").read_text(encoding="utf-8"))
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}


def tracked_sources() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    maintained_roots = ("src/app/", "frontend/src/", "src/frontend/")
    return [
        ROOT / name
        for name in result.stdout.splitlines()
        if Path(name).suffix in EXTENSIONS and name.replace("\\", "/").startswith(maintained_roots)
    ]


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    for path in tracked_sources():
        if not path.exists():
            continue
        relative = path.relative_to(ROOT).as_posix()
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        if lines > 2000 and relative not in BASELINE:
            failures.append(f"NEW_OVERSIZE {relative}: {lines} lines")
        elif lines > 1000:
            warnings.append(f"WARN_OVERSIZE {relative}: {lines} lines")
    for item in warnings:
        print(item)
    for item in failures:
        print(item)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
