import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.app.main import create_app
from tests.utils import default_headers


def _seed_trace_event(client: TestClient, trace_id: str) -> None:
    r = client.post(
        "/api/v1/trace/events",
        headers=default_headers(),
        json=[
            {
                "trace_id": trace_id,
                "event_type": "phase_started",
                "source_type": "agent",
                "source_id": "Orchestrator",
                "payload": {"phase": "EXPLORE"},
            }
        ],
    )
    assert r.status_code == 200


def test_trace_read_requires_auth_in_non_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("TRACE_READ_REQUIRE_AUTH", raising=False)
    app = create_app()
    client = TestClient(app)
    trace_id = "trace-auth-read-prod-1"
    _seed_trace_event(client, trace_id)

    r_no_auth = client.get(f"/api/v1/trace/{trace_id}/events")
    assert r_no_auth.status_code == 401

    r_with_auth = client.get(f"/api/v1/trace/{trace_id}/events", headers=default_headers())
    assert r_with_auth.status_code == 200
    assert isinstance((r_with_auth.json() or {}).get("events"), list)


def test_trace_ws_requires_auth_in_non_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("TRACE_READ_REQUIRE_AUTH", raising=False)
    app = create_app()
    client = TestClient(app)
    trace_id = "trace-auth-ws-prod-1"
    _seed_trace_event(client, trace_id)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/trace/{trace_id}/events/ws") as ws:
            ws.receive_text()

    with client.websocket_connect(
        f"/api/v1/trace/{trace_id}/events/ws",
        headers=default_headers(),
    ) as ws:
        initial = ws.receive_text()
        assert isinstance(initial, str)
