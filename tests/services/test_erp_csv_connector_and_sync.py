import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import set_engine, db_session
from src.app.erp.connectors.csv_inventory import CSVInventoryConnector
from src.app.erp.sync import sync_inventory


def test_csv_connector_and_sync_run(tmp_path):
    # DB
    db_path = tmp_path / "sync.sqlite"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass

    # Create canonical tables for this test DB (SQLite bootstrap will handle core tables, but not new sync tables)
    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS inventory_sync_runs (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT,
                  source TEXT NOT NULL,
                  status TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT,
                  records_seen INTEGER,
                  records_applied INTEGER,
                  error TEXT
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS inventory_external_stock (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT,
                  source TEXT NOT NULL,
                  sku TEXT NOT NULL,
                  warehouse TEXT,
                  stock INTEGER,
                  observed_at TEXT,
                  raw_json TEXT
                )
                """
            )
        )
        db.commit()

    # CSV
    csv_path = tmp_path / "inv.csv"
    csv_path.write_text("sku,stock,warehouse\nSKU1,5,default\n", encoding="utf-8")
    c = CSVInventoryConnector(str(csv_path))

    # dry-run should still create a sync run
    out = sync_inventory(connector=c, tenant_id="t1", dry_run=True)
    assert out["status"] == "dry_run"

    with db_session() as db:
        n = int(db.execute(text("SELECT COUNT(*) FROM inventory_sync_runs")).scalar() or 0)
        assert n == 1

