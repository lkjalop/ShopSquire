from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.main import create_app
from src.app.models.db import db_session, set_engine


def test_admin_inventory_ops_readiness_returns_metrics_and_alerts(monkeypatch, tmp_path):
    db_path = tmp_path / "inv_ops.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass

    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS decision_logs (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT,
                    valid_from TEXT,
                    execution_status TEXT,
                    approval_required INTEGER,
                    retrieved_context TEXT
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS purchase_orders (
                    id TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS decision_trace_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS supplier_score_audits (
                    id TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO decision_logs (id, agent_name, valid_from, execution_status, approval_required, retrieved_context)
                VALUES (:id, :agent, CURRENT_TIMESTAMP, :status, :approval, :ctx)
                """
            ),
            {
                "id": "d1",
                "agent": "inventory_agent",
                "status": "executed",
                "approval": 1,
                "ctx": '{"forecast":{"mape":0.22}}',
            },
        )
        db.execute(
            text(
                """
                INSERT INTO purchase_orders (id, created_at) VALUES ('po1', CURRENT_TIMESTAMP)
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO decision_trace_events (id, event_type, created_at)
                VALUES ('e1', 'inventory_rebalance_suggestion', CURRENT_TIMESTAMP)
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO supplier_score_audits (id, created_at) VALUES ('s1', CURRENT_TIMESTAMP)
                """
            )
        )
        db.commit()

    client = TestClient(create_app())
    r = client.get("/api/v1/admin/inventory/ops/readiness?hours=24", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    body = r.json()
    assert "metrics" in body
    assert "alerts" in body
    m = body["metrics"]
    assert m["reorder_approvals_required"] >= 1
    assert m["po_created_count"] >= 1
    assert m["transfer_suggestions_count"] >= 1
    assert m["supplier_score_audits_count"] >= 1
