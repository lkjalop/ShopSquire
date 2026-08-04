"""Architecture ratchets for the production supplier-email receive boundary."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "app"
BOUNDARY = SRC / "services" / "fulfillment" / "external_comms.py"


def test_production_code_cannot_bypass_receive_email_reply() -> None:
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            name = called.id if isinstance(called, ast.Name) else (
                called.attr if isinstance(called, ast.Attribute) else ""
            )
            if name == "receive_reply" and path != BOUNDARY:
                violations.append(path.relative_to(ROOT).as_posix())

    assert violations == []
