"""SQLite-compatible application of the market schema's Alembic authority."""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text


@lru_cache(maxsize=1)
def _migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260626_market_autonomy_tables.py"
    )
    spec = importlib.util.spec_from_file_location("test_market_autonomy_migration", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("market autonomy migration could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_market_migration(db) -> None:
    """Apply the exported Alembic statements; never call a service bootstrap."""
    migration = _migration()
    for statement in migration.TABLE_STATEMENTS:
        db.execute(text(statement))
    db.execute(text("DROP INDEX IF EXISTS ix_market_signal_dedup"))
    for statement in migration.INDEX_STATEMENTS:
        db.execute(text(statement))

