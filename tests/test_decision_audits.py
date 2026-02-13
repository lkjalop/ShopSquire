import os
import json
import pytest
from tests.utils import default_headers

# Force an in-memory SQLite DB for unit tests to avoid needing Postgres locally
tmp_db = "test_sqlite_db.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{tmp_db}")
os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.app.models.db as dbmod

engine = create_engine(f"sqlite+pysqlite:///{tmp_db}", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)
dbmod.engine = engine
dbmod.SessionLocal = SessionLocal

from src.app.models.db import get_engine
from src.app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import text

app = create_app()
client = TestClient(app, headers=default_headers())


@pytest.fixture(autouse=True)
def enable_decision_writes_env(monkeypatch):
    # Ensure feature flag is enabled for lifecycle tests
    with open("config/feature_flags.json", "w") as f:
        f.write(json.dumps({"DECISION_LOG_WRITES_ENABLED": True}))
    yield


def ensure_tables():
    engine = get_engine()
    # create SQLite-compatible tables for tests (simplified types)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS decision_logs (id TEXT PRIMARY KEY, agent_name TEXT, valid_from TEXT, valid_to TEXT, system_from TEXT, system_to TEXT, input_data TEXT, proposed_action TEXT, policy_version TEXT, approval_required BOOLEAN, execution_status TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS decision_audits (id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT, metadata TEXT, created_at TEXT)"
            )
        )


def test_reopen_and_extend_and_audit(monkeypatch):
    ensure_tables()
    # insert a decision row with a simple text id
    engine = get_engine()
    import uuid
    decision_id = f"dec-{uuid.uuid4()}"
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO decision_logs (id, agent_name, execution_status) VALUES (:id, :agent, :status)"), {"id": decision_id, "agent": "test-agent", "status": "pending"})
    # reopen
    r = client.post(f"/api/v1/decisions/{decision_id}/reopen?actor=tester&comment=need_more_info")
    assert r.status_code == 200
    assert r.json()["reopened"] is True
    # extend
    r2 = client.post(f"/api/v1/decisions/{decision_id}/extend?actor=tester&extend_seconds=3600")
    assert r2.status_code == 200
    assert r2.json()["extended"] is True
    # verify audits
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT action, actor FROM decision_audits WHERE decision_id = :id ORDER BY created_at"), {"id": decision_id}).fetchall()
        actions = [r[0] for r in rows]
    assert "reopen" in actions
    assert "extend" in actions