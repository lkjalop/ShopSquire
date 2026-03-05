#!/usr/bin/env python
"""scripts/check_async_db.py — Detect synchronous db_session() calls inside async route handlers.

Run:
    python scripts/check_async_db.py [path/to/routers]

Exits 0 if no violations found, 1 otherwise.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path


SEARCH_ROOT = sys.argv[1] if len(sys.argv) > 1 else "src/app/routers"


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.violations: list[tuple[int, str]] = []
        self._async_depth = 0

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._async_depth += 1
        self.generic_visit(node)
        self._async_depth -= 1

    def visit_Call(self, node: ast.Call):
        if self._async_depth > 0:
            if (
                isinstance(node.func, ast.Name) and node.func.id == "db_session"
            ) or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "db_session"
            ):
                self.violations.append((node.lineno, ast.unparse(node)))
        self.generic_visit(node)


def check_file(path: Path) -> list[tuple[str, int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    visitor = _Visitor(str(path))
    visitor.visit(tree)
    return [(str(path), ln, snippet) for ln, snippet in visitor.violations]


def main():
    root = Path(SEARCH_ROOT)
    if not root.exists():
        print(f"Path not found: {root}", file=sys.stderr)
        sys.exit(2)

    all_violations: list[tuple[str, int, str]] = []
    for py_file in sorted(root.rglob("*.py")):
        all_violations.extend(check_file(py_file))

    if not all_violations:
        print("check_async_db: OK — no sync db_session() calls in async handlers")
        sys.exit(0)

    print(f"check_async_db: {len(all_violations)} violation(s) found:")
    for fpath, lineno, snippet in all_violations:
        print(f"  {fpath}:{lineno}  {snippet}")
    print()
    print("Fix: wrap the db_session() call using async_db_op() from src.app.models.db,")
    print("or move the DB work into a sync helper function submitted via asyncio.to_thread().")
    sys.exit(1)


if __name__ == "__main__":
    main()
