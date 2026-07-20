from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION = (Path(__file__).resolve().parents[1] / "alembic" / "versions" /
             "20260718_hippograph_tenant_scope.py")


def test_tenant_scope_migration_accepts_runtime_shaped_tables_and_is_idempotent():
    spec = importlib.util.spec_from_file_location("hippograph_tenant_scope_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE decision_trace_events (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL "
            "DEFAULT 'default', created_at TEXT)"
        ))
        connection.execute(text(
            "CREATE TABLE recommendation_decision (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL "
            "DEFAULT 'default', created_at TEXT)"
        ))
        connection.execute(text(
            "CREATE TABLE conversion_event (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL "
            "DEFAULT 'default', order_id TEXT, created_at TEXT)"
        ))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

    for table in ("decision_trace_events", "recommendation_decision", "conversion_event"):
        columns = [column["name"] for column in inspect(engine).get_columns(table)]
        assert columns.count("tenant_id") == 1
    indexes = {index["name"] for index in inspect(engine).get_indexes("conversion_event")}
    assert {"ix_conversion_event_tenant_created", "ux_conversion_event_tenant_order"} <= indexes
