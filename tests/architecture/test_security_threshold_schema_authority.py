from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_threshold_tuning_contains_no_runtime_ddl() -> None:
    source = (ROOT / "src/app/security/threshold_tuning.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    string_literals = {
        node.value.upper()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not any("CREATE TABLE" in value for value in string_literals)
    assert not any("ALTER TABLE" in value for value in string_literals)


def test_head_migration_owns_threshold_and_correction_schema() -> None:
    migration = (
        ROOT / "alembic/versions/20260840_security_threshold_authority.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "20260839_demand_fulfillment_location"' in migration
    assert '"security_threshold_overrides"' in migration
    assert '"email_security_incidents"' in migration
    for column in (
        "ground_truth",
        "analyst_verdict",
        "correction_ts",
        "correction_notes",
    ):
        assert f'"{column}"' in migration
