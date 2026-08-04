from __future__ import annotations

import ast
from pathlib import Path


def test_run_internal_contains_final_governed_execution_return() -> None:
    source = Path("src/app/services/orchestrator.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    orchestrator = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Orchestrator"
    )
    run_internal = next(
        node
        for node in orchestrator.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_internal"
    )
    returns = [node for node in ast.walk(run_internal) if isinstance(node, ast.Return)]

    assert len(returns) >= 3
    assert max(node.lineno for node in returns) > 3800
    assert any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "selected_playbook"
            for target in node.targets
        )
        for node in ast.walk(run_internal)
    )
