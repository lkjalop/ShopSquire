import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_experiment_services_do_not_mutate_schema_at_runtime() -> None:
    for relative in (
        "src/app/services/experiments.py",
        "src/app/services/experiment_ops.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        sql_literals = [
            node.value.upper()
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert not any(
            token in literal
            for literal in sql_literals
            for token in ("CREATE TABLE", "ALTER TABLE", "CREATE INDEX", "DROP TABLE")
        ), f"{relative} contains runtime schema mutation"
