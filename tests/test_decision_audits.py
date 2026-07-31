from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from tests.utils import default_headers


def test_reopen_and_extend_and_audit(monkeypatch):
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "1")
    client = TestClient(create_app(), headers=default_headers())

    # Seed through the migration-owned schema used by the route. Do not replace
    # the process engine or create a competing test-only table definition.
    import uuid

    decision_id = f"dec-{uuid.uuid4()}"
    with db_session() as db:
        db.execute(
            text(
                "INSERT INTO decision_logs (id, agent_name, execution_status) "
                "VALUES (:id, :agent, :status)"
            ),
            {"id": decision_id, "agent": "test-agent", "status": "pending"},
        )
        db.commit()

    # reopen
    r = client.post(f"/api/v1/decisions/{decision_id}/reopen?actor=tester&comment=need_more_info")
    assert r.status_code == 200
    assert r.json()["reopened"] is True
    # extend
    r2 = client.post(f"/api/v1/decisions/{decision_id}/extend?actor=tester&extend_seconds=3600")
    assert r2.status_code == 200
    assert r2.json()["extended"] is True
    # verify audits
    with db_session() as db:
        rows = db.execute(
            text(
                "SELECT action, actor FROM decision_audits "
                "WHERE decision_id = :id ORDER BY created_at"
            ),
            {"id": decision_id},
        ).fetchall()
        actions = [r[0] for r in rows]
    assert "reopen" in actions
    assert "extend" in actions
