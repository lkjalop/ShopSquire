import os
import pathlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.app.models.db as dbmod
from src.app.main import create_app
from tests.utils import default_headers


tmp_db = "test_sqlite_orders_status.sqlite"
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


def test_order_status_transitions_valid():
    _apply_schema()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO orders (id, total_cents, currency, status, created_at, updated_at) VALUES ('o1', 1000, 'USD', 'created', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        )
    r1 = client.post("/api/v1/orders/o1/status", json={"status": "paid"})
    assert r1.status_code == 200
    r2 = client.post("/api/v1/orders/o1/status", json={"status": "shipped"})
    assert r2.status_code == 200
    r3 = client.post("/api/v1/orders/o1/status", json={"status": "delivered"})
    assert r3.status_code == 200


def test_order_status_transitions_invalid():
    _apply_schema()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO orders (id, total_cents, currency, status, created_at, updated_at) VALUES ('o2', 1000, 'USD', 'created', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        )
    r = client.post("/api/v1/orders/o2/status", json={"status": "delivered"})
    assert r.status_code == 400
