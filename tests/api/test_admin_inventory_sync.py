import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from src.app.main import create_app
from src.app.models.db import db_session, set_engine


def test_admin_inventory_csv_sync_writes_sync_run_and_snapshot(monkeypatch, tmp_path):
    csv_path = tmp_path / "inventory.csv"
    csv_path.write_text("sku,stock,warehouse,updated_at\nSKU1,12,default,2026-02-01\nSKU2,0,w2,2026-02-01\n", encoding="utf-8")
    monkeypatch.setenv("CSV_INVENTORY_PATH", str(csv_path))

    db_path = tmp_path / "inv.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    with db_session() as db:
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS supplier_feed_quarantine ("
            "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source TEXT NOT NULL, "
            "sku TEXT NOT NULL, warehouse TEXT, stock INTEGER, risk_score REAL NOT NULL, "
            "reasons_json TEXT NOT NULL, raw_json TEXT NOT NULL, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        ))
        db.commit()

    client = TestClient(create_app())
    r = client.post(
        "/api/v1/admin/inventory/sync",
        json={"connector": "csv", "dry_run": False, "upsert_products": False},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200
    out = r.json()
    assert out.get("source") == "csv"
    assert out.get("status") == "completed"
    assert out.get("records_seen") == 2
    assert out.get("records_applied") == 2

    with db_session() as db:
        run = db.execute(text("SELECT status, records_seen, records_applied FROM inventory_sync_runs WHERE id = :id"), {"id": out["id"]}).fetchone()
        assert run is not None
        assert run[0] == "completed"
        cnt = db.execute(text("SELECT COUNT(1) FROM inventory_external_stock WHERE source = 'csv'")).fetchone()
        assert int(cnt[0] or 0) >= 2

    r2 = client.get("/api/v1/admin/inventory/sync/runs", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200
    assert (r2.json().get("items") or [])

    r3 = client.get("/api/v1/admin/inventory/external_stock/recent?limit=5", headers={"x-api-key": "local-owner-key"})
    assert r3.status_code == 200
    items = r3.json().get("items") or []
    assert any(it.get("sku") == "SKU1" for it in items)

    r4 = client.get("/api/v1/admin/inventory/connectors/summary?limit_samples=3", headers={"x-api-key": "local-owner-key"})
    assert r4.status_code == 200
    summ = r4.json().get("items") or []
    csv = next((x for x in summ if x.get("id") == "csv"), None)
    assert csv is not None
    assert (csv.get("health") or {}).get("ok") is True
    assert csv.get("last_run") is not None
    assert isinstance(csv.get("sample") or [], list)
