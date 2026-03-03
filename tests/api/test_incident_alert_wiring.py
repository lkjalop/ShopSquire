import os
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models import db as dbmod
from src.app.models.db import db_session
from src.app.services import incident_sla_scheduler


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


def test_sla_scheduler_dispatches_alert_once(tmp_path, monkeypatch):
    db_path = str(tmp_path / "incident_sla_alerts.sqlite")
    _init_sqlite(db_path)
    incident_sla_scheduler._ensure_columns()

    now = datetime.now(timezone.utc)
    with db_session() as db:
        db.execute(
            text(
                "INSERT INTO incidents (id, event_id, created_by, severity, title, description, status) "
                "VALUES (:id, :event_id, :created_by, :severity, :title, :description, :status)"
            ),
            {
                "id": "inc-sla-1",
                "event_id": "evt-1",
                "created_by": "tester",
                "severity": "high",
                "title": "SLA breach candidate",
                "description": "desc",
                "status": "open",
            },
        )
        db.execute(
            text("UPDATE incidents SET sla_due_at = :due, sla_status = :st WHERE id = :id"),
            {"id": "inc-sla-1", "due": (now - timedelta(minutes=10)).isoformat(), "st": "active"},
        )
        db.commit()

    calls = []

    def _fake_dispatch(event_type, incident, details=None):
        calls.append({"event_type": event_type, "incident": incident, "details": details})
        return {"ok": True, "sent_total": 1}

    monkeypatch.setattr(incident_sla_scheduler, "dispatch_incident_alert", _fake_dispatch)
    out = incident_sla_scheduler.run_cycle()
    assert int(out.get("breached") or 0) >= 1
    assert len(calls) == 1
    assert calls[0]["event_type"] == "incident_sla_breached"

    # Run a second cycle; dedupe column prevents repeat alert dispatch.
    out2 = incident_sla_scheduler.run_cycle()
    assert int(out2.get("checked") or 0) >= 1
    assert len(calls) == 1

    with db_session() as db:
        row = db.execute(
            text("SELECT sla_status, sla_breach_alerted_at FROM incidents WHERE id = :id LIMIT 1"),
            {"id": "inc-sla-1"},
        ).fetchone()
        assert str(row[0] or "").lower() == "breached"
        assert str(row[1] or "").strip() != ""


def test_runbook_failure_dispatches_alert(tmp_path, monkeypatch):
    db_path = str(tmp_path / "incident_runbook_alerts.sqlite")
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    _init_sqlite(db_path)

    with db_session() as db:
        db.execute(
            text(
                "INSERT INTO incidents (id, event_id, created_by, severity, title, description, status) "
                "VALUES (:id, :event_id, :created_by, :severity, :title, :description, :status)"
            ),
            {
                "id": "inc-rb-1",
                "event_id": "evt-rb-1",
                "created_by": "tester",
                "severity": "critical",
                "title": "Runbook failure candidate",
                "description": "desc",
                "status": "open",
            },
        )
        db.commit()

    from src.app.routers import escalation_room as er

    calls = []

    def _fake_dispatch(event_type, incident, details=None):
        calls.append({"event_type": event_type, "incident": incident, "details": details})
        return {"ok": True, "sent_total": 1}

    def _raise_actions(*args, **kwargs):
        raise RuntimeError("simulated_runbook_failure")

    monkeypatch.setattr(er, "dispatch_incident_alert", _fake_dispatch)
    monkeypatch.setattr(er, "execute_typed_actions", _raise_actions)

    app = create_app()
    client = TestClient(app)
    r = client.post(
        "/api/v1/admin/incidents/inc-rb-1/runbook/execute",
        json={"playbook_id": "PB-SEC-001"},
        headers={"x-api-key": "local-merchant-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    result = body.get("result") or {}
    assert isinstance(result.get("failed"), list) and result.get("failed")
    assert len(calls) == 1
    assert calls[0]["event_type"] == "incident_runbook_failed"

    with db_session() as db:
        row = db.execute(
            text("SELECT runbook_failure_alerted_at FROM incidents WHERE id = :id LIMIT 1"),
            {"id": "inc-rb-1"},
        ).fetchone()
        assert row is not None
        assert str(row[0] or "").strip() != ""


def test_incident_alert_summary_endpoint(tmp_path):
    db_path = str(tmp_path / "incident_alert_summary.sqlite")
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    _init_sqlite(db_path)
    incident_sla_scheduler._ensure_columns()
    from src.app.routers import escalation_room as er
    er._ensure_incident_runtime_tables()

    now_iso = datetime.now(timezone.utc).isoformat()
    with db_session() as db:
        db.execute(
            text(
                "INSERT INTO incidents (id, event_id, created_by, severity, title, description, status) "
                "VALUES (:id, :event_id, :created_by, :severity, :title, :description, :status)"
            ),
            {
                "id": "inc-sum-1",
                "event_id": "evt-sum-1",
                "created_by": "tester",
                "severity": "high",
                "title": "Summary case",
                "description": "desc",
                "status": "open",
            },
        )
        db.execute(
            text(
                "UPDATE incidents SET sla_status = 'breached', sla_due_at = :due, "
                "sla_breach_alerted_at = :sla_alerted, runbook_failure_alerted_at = :rb_alerted WHERE id = :id"
            ),
            {"id": "inc-sum-1", "due": now_iso, "sla_alerted": now_iso, "rb_alerted": now_iso},
        )
        db.commit()

    app = create_app()
    client = TestClient(app)
    r = client.get("/api/v1/admin/incidents/ops/alerts/summary?hours=24&limit=10", headers={"x-api-key": "local-merchant-key"})
    assert r.status_code == 200
    body = r.json()
    totals = body.get("totals") or {}
    assert int(totals.get("sla_breach_alerts") or 0) >= 1
    assert int(totals.get("runbook_failure_alerts") or 0) >= 1
    recent = body.get("recent") or []
    assert any(str(x.get("incident_id") or "") == "inc-sum-1" for x in recent if isinstance(x, dict))
