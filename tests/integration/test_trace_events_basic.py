import time

from fastapi.testclient import TestClient


def test_trace_events_append_and_list():
    from src.app.main import create_app

    app = create_app()
    client = TestClient(app)

    trace_id = f"test-trace-{int(time.time())}"
    ev = [{"trace_id": trace_id, "event_type": "test_event", "payload": {"msg": "hello"}}]
    r = client.post("/api/v1/trace/events", json=ev, headers={"x-api-key": "local-developer-key"})
    assert r.status_code == 200

    r2 = client.get(f"/api/v1/trace/{trace_id}/events", headers={"x-api-key": "local-developer-key"})
    assert r2.status_code == 200
    body = r2.json()
    assert any(e.get("event_type") == "test_event" for e in (body.get("events") or []))

