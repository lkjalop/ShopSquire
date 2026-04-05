import os
import pathlib

from tests.utils import default_headers

tmp_db = "test_sqlite_orders.sqlite"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_db}"
os.environ["DATABASE_URL_RO"] = f"sqlite+pysqlite:///{tmp_db}"
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

from fastapi.testclient import TestClient
from src.app.main import create_app

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


def test_order_history_paging():
    _apply_schema()
    # Override app.state.engine and dbmod.engine so HTTP handlers read/write
    # the same StaticPool engine as our direct inserts.
    import src.app.models.db as _dbmod
    orig_app_engine = getattr(app.state, "engine", None)
    orig_dbmod_engine = _dbmod.engine
    app.state.engine = engine
    _dbmod.engine = engine
    try:
        with engine.begin() as conn:
            for i in range(5):
                order_id = f"order-{i}"
                conn.execute(
                    text("INSERT OR REPLACE INTO orders (id, total_cents, currency, status, created_at, updated_at) VALUES (:id, :total, 'USD', 'created', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                    {"id": order_id, "total": 10000 + i * 100},
                )
                conn.execute(
                    text("INSERT OR REPLACE INTO order_sessions (id, uid, order_id, created_at) VALUES (:id, :uid, :order_id, CURRENT_TIMESTAMP)"),
                    {"id": f"session-{i}", "uid": "paging-user", "order_id": order_id},
                )
        r = client.get("/api/v1/orders/history", params={"uid": "paging-user", "limit": 2, "offset": 0})
        assert r.status_code == 200
        data = r.json()
        assert len(data.get("orders", [])) == 2
        assert data.get("has_more") is True
        r2 = client.get("/api/v1/orders/history", params={"uid": "paging-user", "limit": 2, "offset": data.get("next_offset", 2)})
        assert r2.status_code == 200
        data2 = r2.json()
        assert len(data2.get("orders", [])) == 2
    finally:
        app.state.engine = orig_app_engine
        _dbmod.engine = orig_dbmod_engine
        from tests.conftest import _SINGLETONS, _SINGLETONS_LOCK
        with _SINGLETONS_LOCK:
            for _app_inst in _SINGLETONS.values():
                try:
                    _app_inst.state.engine = orig_dbmod_engine
                except Exception:
                    pass
