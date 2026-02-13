import os
import pathlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.app.models.db as dbmod
from src.app.main import create_app
from tests.utils import default_headers


tmp_db = "test_sqlite_admin_overview.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{tmp_db}")
os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

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
    schema_path = pathlib.Path("db/schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()


def test_admin_overview_returns_series():
    _apply_schema()
    r = client.get("/api/v1/admin/overview")
    assert r.status_code == 200
    data = r.json()
    assert "decision_series" in data
    assert isinstance(data.get("decision_series"), list)
