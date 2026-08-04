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
                      heartbeat_at TEXT,
                      budget_deadline_at TEXT,
                      outcome_type TEXT,
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
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS supplier_feed_quarantine (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  source TEXT NOT NULL,
                  sku TEXT NOT NULL,
                  warehouse TEXT,
                  stock INTEGER,
                  risk_score REAL NOT NULL,
                  reasons_json TEXT NOT NULL,
                  raw_json TEXT NOT NULL,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
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

        # Another tenant's low baseline must not influence tenant t1.
        db.execute(text(
            "INSERT INTO inventory_external_stock "
            "(id,tenant_id,source,sku,warehouse,stock,observed_at) "
            "VALUES ('other-baseline','t2','csv','SKU1','default',1,'2026-01-01')"
        ))
        db.commit()

    csv_path.write_text(
        "sku,stock,warehouse,updated_at\n"
        "SKU1,100,default,2026-02-01T00:00:00Z\n",
        encoding="utf-8",
    )
    first = sync_inventory(connector=c, tenant_id="t1", dry_run=False)
    assert first["status"] == "completed"
    assert first["records_applied"] == 1
    assert first["records_quarantined"] == 0

    csv_path.write_text(
        "sku,stock,warehouse,updated_at\n"
        "SKU1,500,default,2026-02-02T00:00:00Z\n",
        encoding="utf-8",
    )
    second = sync_inventory(connector=c, tenant_id="t1", dry_run=False)
    assert second["status"] == "completed"
    assert second["records_applied"] == 0
    assert second["records_quarantined"] == 1
    with db_session() as db:
        active_500 = db.execute(text(
            "SELECT COUNT(*) FROM inventory_external_stock "
            "WHERE tenant_id='t1' AND source='csv' AND sku='SKU1' AND stock=500"
        )).scalar()
        quarantined_500 = db.execute(text(
            "SELECT COUNT(*) FROM supplier_feed_quarantine "
            "WHERE tenant_id='t1' AND source='csv' AND sku='SKU1' AND stock=500"
        )).scalar()
        assert active_500 == 0
        assert quarantined_500 == 1

    class _UnavailableConnector:
        def name(self):
            return "unavailable-test"

        def health(self):
            return {"ok": False, "error": "credentials_missing"}

        def fetch_inventory(self, *, tenant_id=None):
            raise AssertionError("fetch must not run after failed health")

    unavailable = sync_inventory(
        connector=_UnavailableConnector(), tenant_id="t1", dry_run=False,
    )
    assert unavailable["status"] == "unavailable"
    with db_session() as db:
        persisted = db.execute(
            text("SELECT status, error FROM inventory_sync_runs WHERE id=:id"),
            {"id": unavailable["id"]},
        ).fetchone()
        assert persisted[0] == "unavailable"
        assert "credentials_missing" in persisted[1]
