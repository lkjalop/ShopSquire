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


def evaluate_source_sizes(
    *, root: Path = ROOT, baseline: dict[str, int] | None = None,
) -> tuple[list[str], list[str]]:
    """Return warnings and failures for the maintained-source size ratchet.

    Existing oversized files are debt, not permanent exemptions. Their recorded
    size is a ceiling which may only move down; new files still fail above 2,000
    lines and warn above 1,000.
    """
    limits = BASELINE if baseline is None else baseline
    failures: list[str] = []
    warnings: list[str] = []
    paths = tracked_sources() if root == ROOT else [
        path for path in root.rglob("*") if path.suffix in EXTENSIONS
    ]
    for path in paths:
        if not path.exists():
            continue
        relative = path.relative_to(root).as_posix()
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        recorded_ceiling = limits.get(relative)
        if recorded_ceiling is not None and lines > recorded_ceiling:
            failures.append(
                f"OVERSIZE_GROWTH {relative}: {lines} lines exceeds ceiling {recorded_ceiling}"
            )
        elif lines > 2000 and recorded_ceiling is None:
            failures.append(f"NEW_OVERSIZE {relative}: {lines} lines")
        if lines > 1000:
            warnings.append(f"WARN_OVERSIZE {relative}: {lines} lines")
    return warnings, failures


def main() -> int:
    warnings, failures = evaluate_source_sizes()
    for item in warnings:
        print(item)
    for item in failures:
        print(item)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
