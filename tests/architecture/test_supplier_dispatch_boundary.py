import ast
from pathlib import Path


def test_application_code_cannot_call_retired_standalone_supplier_dispatch():
    """Production sends must use fulfillment external_comms -> durable outbox."""
    violations: list[str] = []
    for path in Path("src/app").rglob("*.py"):
        if path.as_posix().endswith("services/supplier_communication.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = str(node.module or "")
                if module == "src.app.services.supplier_communication" and any(
                    alias.name == "dispatch_supplier_message" for alias in node.names
                ):
                    violations.append(path.as_posix())
    assert violations == []
