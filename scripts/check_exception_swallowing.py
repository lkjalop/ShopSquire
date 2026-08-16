"""Freeze broad exception debt in the two highest-risk composition modules."""
from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads(
    (ROOT / "config" / "exception_swallowing_baseline.json").read_text(encoding="utf-8")
)


def exception_counts(path: Path) -> tuple[int, int]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    broad = silent = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        broad_handler = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
        )
        if not broad_handler:
            continue
        broad += 1
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            silent += 1
    return broad, silent


def evaluate_exception_debt(*, root: Path = ROOT, baseline=None) -> list[str]:
    limits = BASELINE if baseline is None else baseline
    failures: list[str] = []
    for relative, policy in limits.items():
        broad, silent = exception_counts(root / relative)
        if broad > int(policy["broad_handlers"]):
            failures.append(
                f"BROAD_EXCEPTION_GROWTH {relative}: {broad} > {policy['broad_handlers']}"
            )
        if silent > int(policy["silent_pass_handlers"]):
            failures.append(
                f"SILENT_EXCEPTION_GROWTH {relative}: {silent} > {policy['silent_pass_handlers']}"
            )
    return failures


def main() -> int:
    failures = evaluate_exception_debt()
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
