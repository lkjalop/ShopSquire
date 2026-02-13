import os
import json

from tests.utils import default_headers

# Force SQLite for this test file
tmp_db = "test_sqlite_bitemporal.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{tmp_db}")
os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.app.models.db as dbmod

engine = create_engine(
    f"sqlite+pysqlite:///{tmp_db}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, future=True)
dbmod.engine = engine
dbmod.SessionLocal = SessionLocal

from src.app.main import create_app
from fastapi.testclient import TestClient

app = create_app()
client = TestClient(app, headers=default_headers())


def _enable_flags():
    with open("config/feature_flags.json", "w", encoding="utf-8") as f:
        json.dump({"DECISION_LOG_WRITES_ENABLED": True}, f)


def _ensure_tables():
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS decision_logs (id TEXT PRIMARY KEY, agent_name TEXT, valid_from TEXT, valid_to TEXT, system_from TEXT, system_to TEXT, input_data TEXT, proposed_action TEXT, policy_version TEXT, approval_required BOOLEAN, execution_status TEXT)"
            )
        )


def test_decision_query_includes_bitemporal_fields():
    _enable_flags()
    _ensure_tables()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO decision_logs (id, agent_name, valid_from, system_from, input_data, proposed_action, policy_version, approval_required, execution_status) "
                "VALUES ('bitemp-1', 'rec-agent', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '{}', '{}', 'v1', 0, 'executed')"
            )
        )
    resp = client.get("/api/v1/decisions/query")
    assert resp.status_code == 200
    data = resp.json()
    rows = data.get("results") or []
    assert any(r.get("id") == "bitemp-1" for r in rows)
    row = next(r for r in rows if r.get("id") == "bitemp-1")
    assert row.get("valid_from")
    assert row.get("system_from")
