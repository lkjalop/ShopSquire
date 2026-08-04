from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


MIGRATION = (Path(__file__).resolve().parents[1] / "alembic" / "versions" /
             "20260720_product_embeddings_reconcile.py")


def test_reconcile_creates_idempotent_sqlite_embedding_contract():
    spec = importlib.util.spec_from_file_location("product_embeddings_reconcile", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

    columns = {column["name"] for column in inspect(engine).get_columns("product_embeddings")}
    assert columns == {"product_id", "embedding", "updated_at"}
