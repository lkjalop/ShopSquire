import os
import json
import pathlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.app.models.db as dbmod
from src.app.main import create_app
from tests.utils import default_headers


tmp_db = "test_sqlite_security_paths.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{tmp_db}")
os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
os.environ.setdefault("SECURITY_OBSERVER_SYNC", "1")
os.environ.setdefault("DISABLE_TRACING", "1")
os.environ["SKIP_OBSERVER_ENDPOINTS"] = ""

engine = create_engine(
    f"sqlite+pysqlite:///{tmp_db}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, future=True)
dbmod.engine = engine
dbmod.SessionLocal = SessionLocal

app = create_app()
client = TestClient(app, headers=default_headers())


def _apply_schema():
    # Collection imports other app modules that replace the process-global
    # engine. Rebind both seams at test execution so observer persistence is
    # proven against the same tenant/test database the assertion reads.
    dbmod.set_engine(engine)
    app.state.engine = engine
    schema_path = pathlib.Path("db/schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()


def _latest_event_for_path(path: str):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT details FROM security_events WHERE path = :path ORDER BY event_time DESC LIMIT 1"),
            {"path": path},
        ).fetchone()
    return json.loads(row[0]) if row else None


def test_observer_logs_for_recommend():
    _apply_schema()
    r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "laptop"})
    assert r.status_code == 200
    details = _latest_event_for_path("/api/v1/recommend/suggest")
    assert details and details.get("payload")


def test_observer_logs_for_support():
    _apply_schema()
    r = client.post("/api/v1/support/answer", params={"question": "need help"})
    assert r.status_code == 200
    details = _latest_event_for_path("/api/v1/support/answer")
    assert details and details.get("payload")
