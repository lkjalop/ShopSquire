"""Debug script to trace engine state across chaos test + api test scenario."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_file = "tmp/test_debug_run.sqlite"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_file}"

import src.app.main as _m
import threading

_SINGLETONS: dict = {}
_SINGLETONS_LOCK = threading.Lock()


def _get_or_create_app_for_url():
    db_url = os.environ.get("DATABASE_URL", "")
    with _SINGLETONS_LOCK:
        if db_url not in _SINGLETONS:
            _SINGLETONS[db_url] = _m._original_create_app()
        return _SINGLETONS[db_url]


_m._original_create_app = _m.create_app
_m.create_app = _get_or_create_app_for_url

from src.app.models.db import get_engine, set_engine, db_session
from sqlalchemy import text

print("=== Creating singleton ===")
app = _m.create_app()
print(f"Session engine id: {id(get_engine())} url: {get_engine().url}")
print(f"app.state.engine id: {id(app.state.engine)} url: {app.state.engine.url}")

print("\n=== Chaos test calls create_app (same singleton) ===")
app2 = _m.create_app()
print(f"app2 is app: {app2 is app}")

from fastapi.testclient import TestClient

print("\n=== Chaos test makes TestClient request ===")
client = TestClient(app2)
r = client.get("/api/v1/admin/overview", headers={"x-api-key": "local-developer-key"})
print(f"Request status: {r.status_code}")
print(f"After request - module engine id: {id(get_engine())}")
print(f"After request - app.state.engine id: {id(app2.state.engine)}")
print(f"Engines match: {get_engine() is app2.state.engine}")

print("\n=== BI test inserts data via db_session() ===")
try:
    with db_session() as db:
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS decision_trace_events "
            "(id TEXT PRIMARY KEY, trace_id TEXT, event_type TEXT NOT NULL, "
            "source_type TEXT, source_id TEXT, target_type TEXT, target_id TEXT, "
            "payload TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        ))
        db.execute(text(
            "INSERT OR REPLACE INTO decision_trace_events "
            "(id, trace_id, event_type, source_type, source_id) "
            "VALUES ('mh-1', 'trace-1', 'memory_health', 'agent', 'Conversation_Memory_Agent')"
        ))
        db.commit()
    print("INSERT succeeded")
except Exception as e:
    print(f"INSERT FAILED: {e}")

with get_engine().connect() as conn:
    cnt = conn.execute(text("SELECT COUNT(*) FROM decision_trace_events")).scalar()
    print(f"Count via module engine: {cnt}")

print("\n=== BI test makes API request with TestClient ===")
app3 = _m.create_app()
print(f"app3 is app: {app3 is app}")
client3 = TestClient(app3, headers={"x-api-key": "local-merchant-key", "x-tenant-id": "default"})
r3 = client3.get("/api/v1/admin/bi/memory-health?days=14")
print(f"Request status: {r3.status_code}")
body = r3.json()
totals = body.get("totals") or {}
print(f"events in response: {totals.get('events')}")
print(f"Full body keys: {list(body.keys())}")
