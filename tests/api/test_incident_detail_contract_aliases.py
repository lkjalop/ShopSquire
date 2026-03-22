import json
import os

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models import db as dbmod
from src.app.models.db import db_session


def _init_sqlite(db_path: str) -> None:
    from sqlalchemy import create_engine

    eng = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    dbmod.set_engine(eng)
    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                  id TEXT PRIMARY KEY,
                  event_id TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  created_by TEXT,
                  severity TEXT,
                  title TEXT,
                  description TEXT,
                  status TEXT DEFAULT 'open'
                )
                """
            )
        )
        db.commit()


def test_admin_incident_detail_exposes_compatibility_aliases(tmp_path):
    db_path = str(tmp_path / "incident_contract.sqlite")
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    _init_sqlite(db_path)

    from src.app.routers import escalation_room as er

    er._ensure_incident_runtime_tables()

    incident_id = "inc-contract-1"
    event_id = "trace-contract-1"
    description = {
        "reason": "policy_gate",
        "trace_id": event_id,
        "case_id": "approval-123",
        "context": {"foo": "bar"},
    }
    with db_session() as db:
        db.execute(
            text(
                "INSERT INTO incidents (id, event_id, created_by, severity, title, description, status) "
                "VALUES (:id, :event_id, :created_by, :severity, :title, :description, :status)"
            ),
            {
                "id": incident_id,
                "event_id": event_id,
                "created_by": "tester",
                "severity": "high",
                "title": "Contract incident",
                "description": json.dumps(description),
                "status": "open",
            },
        )
        db.commit()

    app = create_app()
    client = TestClient(app)
    r = client.get(f"/api/v1/admin/incidents/{incident_id}", headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("id") == incident_id
    assert body.get("event_id") == event_id
    assert body.get("eventId") == event_id
    assert body.get("trace_id") == event_id
    assert body.get("traceId") == event_id
    assert body.get("reason") == "policy_gate"
    assert body.get("case_id") == "approval-123"
    assert body.get("caseId") == "approval-123"
    assert body.get("description", {}).get("reason") == "policy_gate"
    assert body.get("description_raw")


def test_admin_incident_detail_resolves_event_id_lookup(tmp_path):
    db_path = str(tmp_path / "incident_contract_event_lookup.sqlite")
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    _init_sqlite(db_path)

    from src.app.routers import escalation_room as er

    er._ensure_incident_runtime_tables()

    incident_id = "inc-contract-2"
    event_id = "trace-contract-2"
    description = {
        "reason": "email_lab_manual_escalation",
        "trace_id": event_id,
        "case_id": "approval-456",
    }
    with db_session() as db:
        db.execute(
            text(
                "INSERT INTO incidents (id, event_id, created_by, severity, title, description, status) "
                "VALUES (:id, :event_id, :created_by, :severity, :title, :description, :status)"
            ),
            {
                "id": incident_id,
                "event_id": event_id,
                "created_by": "tester",
                "severity": "medium",
                "title": "Contract incident event lookup",
                "description": json.dumps(description),
                "status": "open",
            },
        )
        db.commit()

    app = create_app()
    client = TestClient(app)
    r = client.get(f"/api/v1/admin/incidents/{event_id}", headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("id") == incident_id
    assert body.get("event_id") == event_id
    assert body.get("trace_id") == event_id
    assert body.get("reason") == "email_lab_manual_escalation"
