import os
import importlib
from fastapi.testclient import TestClient


def _make_test_client(tmp_path):
    # create a per-test sqlite DB and set env var before importing app
    db_file = tmp_path / "test_admin_interleaving.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_file}"
    # reload DB module if present to ensure engine reinitialization
    try:
        import src.app.models.db as dbmod
        importlib.reload(dbmod)
    except Exception:
        pass
    # create app after env is set
    from src.app.main import create_app

    app = create_app()
    return TestClient(app)


def test_admin_interleaving_summary_endpoints(tmp_path):
    client = _make_test_client(tmp_path)
    trace_id = "e2e-demo-trace"
    headers = {"x-api-key": "local-developer-key"}

    events = [
        {"trace_id": trace_id, "event_type": "tier_decision", "source_type": "orchestrator", "source_id": "tier_router", "payload": {"tier": 2, "reason": "e2e", "tool_budget": 4}},
        {"trace_id": trace_id, "event_type": "tool_budget", "source_type": "orchestrator", "source_id": "parallel_block", "payload": {"remaining": 2}},
        {"trace_id": trace_id, "event_type": "interleaving_event", "source_type": "orchestrator", "source_id": "InterleavingController", "payload": {"event": "tool_called", "tool_name": "retrieve_context"}},
        {"trace_id": trace_id, "event_type": "agent_invocation", "source_type": "orchestrator", "source_id": "agent_runner", "target_type": "agent", "target_id": "Inventory_Agent", "payload": {"phase": "phase2", "agent": "Inventory_Agent", "latency_ms": 50}}
    ]

    r = client.post("/api/v1/trace/events", json=events, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body.get("stored", 0) >= 1

    r2 = client.get(f"/api/v1/admin/interleaving/{trace_id}/summary", headers=headers)
    assert r2.status_code == 200
    j = r2.json()
    assert j and "summary" in j

    r3 = client.get(f"/api/v1/trace/{trace_id}/summary/by_time?bucket_seconds=1", headers=headers)
    assert r3.status_code == 200
    jb = r3.json()
    assert "buckets" in jb
