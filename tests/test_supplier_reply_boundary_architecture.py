import ast
from pathlib import Path


def test_runtime_code_cannot_call_low_level_supplier_receive_reply():
    root = Path(__file__).resolve().parents[1] / "src" / "app"
    violations = []
    owner = (root / "services" / "fulfillment" / "external_comms.py").resolve()
    for path in root.rglob("*.py"):
        if path.resolve() == owner:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "receive_reply":
                violations.append(f"{path.relative_to(root)}:{node.lineno}")
            elif isinstance(fn, ast.Name) and fn.id == "receive_reply":
                violations.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not violations, (
        "Supplier email must enter through receive_email_reply(), not the low-level transition: "
        + ", ".join(violations)
    )
