from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260714_draft_orders_version.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("draft_orders_version_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_migration_repairs_existing_cart_table():
    migration = _load_migration()
    assert migration.down_revision == "20260713_draft_orders_tenant"
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE draft_orders (id TEXT PRIMARY KEY, customer_id TEXT, line_items TEXT NOT NULL)"
        ))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

    columns = {column["name"]: column for column in inspect(engine).get_columns("draft_orders")}
    assert "version" in columns
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO draft_orders (id, customer_id, line_items) VALUES ('d1', 'u1', '[]')"
        ))
        assert connection.execute(text("SELECT version FROM draft_orders WHERE id='d1'")).scalar() == 0
