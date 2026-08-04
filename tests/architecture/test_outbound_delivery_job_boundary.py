import ast
from pathlib import Path


def test_operator_outbound_endpoint_does_not_transmit_inline():
    path = Path("src/app/routers/fulfillment_cases.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    route = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "outbound_process"
    )
    calls = {
        node.func.attr
        for node in ast.walk(route)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "process_pending" not in calls
    assert "send" not in calls
    assert "apply_async" in calls


def test_outbound_queue_has_no_runtime_schema_creation_calls():
    path = Path("src/app/services/fulfillment/outbound_queue.py")
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "execute":
            continue
        first = node.args[0]
        assert not (
            isinstance(first, ast.Call)
            and isinstance(first.func, ast.Name)
            and first.func.id == "text"
            and first.args
            and isinstance(first.args[0], ast.Name)
            and first.args[0].id == "_DDL"
        )
