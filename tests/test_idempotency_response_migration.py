from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260714_idempotency_response.py"


def test_legacy_idempotency_table_gains_fingerprint_and_response_columns():
    spec = importlib.util.spec_from_file_location("idempotency_response_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20260714_draft_orders_version"

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE idempotency_keys (key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        ))
        connection.execute(text("INSERT INTO idempotency_keys (key) VALUES ('legacy')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

    columns = {column["name"] for column in inspect(engine).get_columns("idempotency_keys")}
    assert {"key", "fingerprint", "response_status", "response_body", "created_at"} <= columns
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT fingerprint FROM idempotency_keys WHERE key='legacy'"
        )).scalar_one() == ""
