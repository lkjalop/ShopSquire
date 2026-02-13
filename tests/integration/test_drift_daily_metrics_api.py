import json
import os
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import db_session, set_engine
from src.app.models.init_db import ensure_metadata


def _bootstrap_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "drift.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    ensure_metadata()


def test_drift_daily_metrics_recompute_and_query(monkeypatch, tmp_path):
    monkeypatch.setenv("DISABLE_TRACING", "1")
    _bootstrap_sqlite(tmp_path, monkeypatch)

    # Seed one email incident + one CV evidence bundle.
    today = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO email_security_incidents
                  (id, tenant_id, provider, supplier_key_hash, conversation_id_hash, message_id_hash,
                   ticket_id, severity, risk_band, tags_json, reasons_json, evidence_json,
                   playbook_id, playbook_title, ticket_created, ticket_rate_limited, ticket_deduped, created_at)
                VALUES
                  ('inc-1', NULL, 'gmail', 'sup', 'conv', 'msg', NULL, 'warning', 'medium',
                   '[]', '[]', '{}', 'PB-EMAIL-002', 'Reply-To Mismatch', 0, 0, 0, :ts)
                """
            ),
            {"ts": today},
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO evidence_bundles (id, case_id, bundle_json, created_at)
                VALUES (:id, :case_id, :bundle_json, :ts)
                """
            ),
            {
                "id": "ev-1",
                "case_id": "case-1",
                "bundle_json": json.dumps(
                    {
                        "evidence_id": "ev-1",
                        "sku": "SKU-1",
                        "cv": {"pack_id": "electronics", "fields": {"order_id": "ABCD-1"}},
                        "cv_tier2": {"pack_id": "agnostic_v1", "images": [{"forensics": {"manipulation_score": 0.72}}]},
                    }
                ),
                "ts": today,
            },
        )
        db.commit()

    from src.app.main import create_app

    client = TestClient(create_app(), headers={"x-api-key": os.getenv("OWNER_API_KEY", "local-owner-key")})
    r = client.post("/api/v1/admin/drift/daily/recompute?days=7")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert int(body.get("written") or 0) >= 1

    q = client.get("/api/v1/admin/drift/daily?days=7")
    assert q.status_code == 200
    items = (q.json() or {}).get("items") or []
    assert any(it.get("domain") == "email_security" for it in items)
    assert any(it.get("domain") == "cv" for it in items)
    assert any(it.get("metric_key") == "manipulation_score_bucket_total" for it in items)

    c = client.post("/api/v1/admin/drift/calibration/recompute?days=7")
    assert c.status_code == 200
    assert c.json().get("status") == "ok"

    a = client.get("/api/v1/admin/drift/calibration/alerts?days=7")
    assert a.status_code == 200
    assert "alerts" in (a.json() or {})

    l = client.get("/api/v1/admin/drift/recommendation/ltr_snapshot")
    assert l.status_code == 200
    assert "items" in (l.json() or {})
