import json

from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


app = create_app()
client = TestClient(app, headers=default_headers())


def test_trace_events_ws_streams_initial_and_live_events():
    trace_id = "trace-ws-live-1"
    r0 = client.post(
        "/api/v1/trace/events",
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
    assert r0.status_code == 200

    with client.websocket_connect(f"/api/v1/trace/{trace_id}/events/ws") as ws:
        initial = json.loads(ws.receive_text())
        assert isinstance(initial, list)
        assert any(str((e or {}).get("event_type") or "") == "phase_started" for e in initial if isinstance(e, dict))

        r1 = client.post(
            "/api/v1/trace/events",
            json=[
                {
                    "trace_id": trace_id,
                    "event_type": "agent_invocation",
                    "source_type": "agent",
                    "source_id": "NLP_Search_Agent",
                    "payload": {"agent": "NLP_Search_Agent"},
                }
            ],
        )
        assert r1.status_code == 200
        live = json.loads(ws.receive_text())
        assert isinstance(live, list) and live
        assert str((live[0] or {}).get("event_type") or "") == "agent_invocation"
