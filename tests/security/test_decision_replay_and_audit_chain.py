import json
import uuid

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.persistence import write_audit_and_event


def _owner_headers():
    return {"x-api-key": "local-owner-key"}


def test_decision_replay_not_found_and_causal_empty():
    app = create_app()
    client = TestClient(app)
    r = client.get(f"/api/v1/decisions/replay/{uuid.uuid4()}", headers=_owner_headers())
    assert r.status_code == 404
    c = client.get(f"/api/v1/decisions/trace/{uuid.uuid4()}/causal", headers=_owner_headers())
    assert c.status_code == 200
    body = c.json()
    assert "nodes" in body and "edges" in body


def test_audit_chain_populates_from_audit_write():
    decision_id = f"test:{uuid.uuid4()}"
    ok = write_audit_and_event(decision_id, "unit_test_audit", "tester", {"k": "v"})
    assert ok is True
    with db_session() as db:
        row = db.execute(
            "SELECT COUNT(*) FROM audit_log_chain WHERE source_type = :st AND source_id = :sid",
            {"st": "decision.audit", "sid": decision_id},
        ).fetchone()
    assert row and int(row[0] or 0) >= 1
