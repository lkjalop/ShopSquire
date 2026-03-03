from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from tests.utils import default_headers


def _seed_rows() -> None:
    with db_session() as db:
        db.execute(
            text(
                "INSERT OR REPLACE INTO orders (id,total_cents,status,created_at) VALUES "
                "('bi-o1', 150000, 'paid', '2026-01-02 10:00:00'),"
                "('bi-o2', 50000, 'refunded', '2026-01-03 11:00:00'),"
                "('bi-o3', 90000, 'chargeback', '2026-01-04 12:00:00')"
            )
        )
        db.execute(
            text(
                "INSERT OR REPLACE INTO decision_logs "
                "(id,agent_name,valid_from,approval_required,execution_status,policy_version,input_data,proposed_action) VALUES "
                "('bi-d1','Fraud_Agent','2026-01-02 09:00:00',0,'executed','v1','{}','{}'),"
                "('bi-d2','Fraud_Agent','2026-01-03 09:00:00',1,'rejected','v2','{}','{}'),"
                "('bi-d3','Policy_Agent','2026-01-04 09:00:00',0,'approved','v2','{}','{}')"
            )
        )
        db.execute(
            text(
                "INSERT OR REPLACE INTO security_events (id,event_time,severity,details,correction_ts,verdict_score) VALUES "
                "('bi-s1','2026-01-03 13:00:00','high','phish campaign observed','2026-01-03 13:30:00',88),"
                "('bi-s2','2026-01-04 13:00:00','critical','prompt injection attempt in qr','2026-01-04 13:20:00',95)"
            )
        )
        db.commit()


def test_admin_bi_executive_pulse_shape():
    _seed_rows()
    app = create_app()
    client = TestClient(app, headers=default_headers())
    resp = client.get("/api/v1/admin/bi/executive-pulse", params={"start": "2026-01-01", "end": "2026-01-08"})
    assert resp.status_code == 200
    body = resp.json()
    assert "kpis" in body
    assert "trend_overlays" in body
    assert "agentic_ops" in body
    assert "security_incursions_matrix" in body
    assert "decision_replay" in body
    assert body["kpis"]["revenue"] >= 0


def test_admin_bi_query_agent_template_guardrails():
    _seed_rows()
    app = create_app()
    client = TestClient(app, headers=default_headers())
    ok = client.post(
        "/api/v1/admin/bi/query-agent",
        json={"query": "show refund rate and approval rate", "start": "2026-01-01", "end": "2026-01-08"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body.get("status") == "ok"
    assert body.get("guardrails", {}).get("template_only") is True

