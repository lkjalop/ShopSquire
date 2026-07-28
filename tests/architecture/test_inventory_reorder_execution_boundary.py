import ast
from pathlib import Path


ROOT = Path("src/app")
ALLOWED = Path("src/app/services/inventory_reorder_execution.py")


def test_only_governed_boundary_calls_inventory_execute_reorder():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if path == ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "execute_reorder":
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_inventory_http_boundary_accepts_only_proposal_identity():
    source = Path("src/app/routers/inventory.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    request_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ReorderRequest"
    )
    fields = {
        node.target.id
        for node in request_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert fields == {"proposal_id"}
