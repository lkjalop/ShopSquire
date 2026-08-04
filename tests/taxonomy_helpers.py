from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def apply_taxonomy_migration(db) -> None:
    """Build taxonomy fixture schema through the deployment migration."""
    operations = Operations(MigrationContext.configure(db.connection()))
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260711_taxonomy_grounding.py"
    )
    spec = importlib.util.spec_from_file_location("taxonomy_grounding_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    original = module.op
    module.op = operations
    try:
        module.upgrade()
    finally:
        module.op = original
    db.commit()
