"""Freeze async shopping-case handlers that still receive synchronous sessions."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SYNC_DB_ASYNC_HANDLERS = {
    "accept_requirement_proposal",
    "resolve_case_evidence_source",
    "approve_case_publisher_candidate",
    "research_shopping_case",
}


def test_async_route_sync_session_debt_cannot_grow():
    path = ROOT / "src" / "app" / "routers" / "shopping_cases.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {
        node.name
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and any(
            argument.arg == "db"
            for argument in (*node.args.args, *node.args.kwonlyargs)
        )
    }
    assert found == EXPECTED_SYNC_DB_ASYNC_HANDLERS
