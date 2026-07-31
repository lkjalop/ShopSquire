import os
import time
from fastapi.testclient import TestClient

from src.app.main import create_app


def test_v2_recommend_surfaces_decision_and_feedback_trace(monkeypatch):
    # Ensure decision traces are enabled for the test run
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "1")
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")

    app = create_app()
    client = TestClient(app)

    headers = {"x-api-key": "local-merchant-key"}

    # Open-ended query (no budget/brands/specs) should trigger NQE early return
    resp = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": "test-user-1", "query": "I'm thinking about a laptop"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, dict)
    # Trace id should be present; clarifying questions may be emitted into the trace stream
    trace_id = data.get("trace_id") or data.get("decision_trace_id")
    assert trace_id
    # V2 owns decision evidence on the typed response. A model proposal is
    # optional: deterministic routing is valid and must not fabricate one.
    decision = data.get("decision")
    model_selection = data.get("model_selection")
    if isinstance(decision, dict):
        execution_steps = data.get("execution_steps") or []
        assert any(step.get("authority") == "authorizes" for step in execution_steps)
        assert any(step.get("authority") == "presents" for step in execution_steps)
        if model_selection is not None:
            assert isinstance(model_selection, dict)
            assert model_selection.get("selected")
            assert model_selection.get("authority") == "proposes"
        assert data.get("execution_mode") in {"v2_served", "v2_compatibility"}
    else:
        # An unseeded shard may not have authoritative catalog evidence. V2
        # must degrade honestly and must not fabricate a decision/model.
        assert data.get("products") == []
        assert data.get("action_executed") is False
        assert model_selection is None

    # Poll the decision trace query endpoint until events appear or timeout
    events = []
    deadline = time.time() + 5.0
    while time.time() < deadline:
        q = client.get(f"/api/v1/decisions/{trace_id}/query", params={"include_events": "true"}, headers=headers)
        if q.status_code == 200:
            body = q.json()
            events = body.get("events") or []
            if events:
                break
        time.sleep(0.25)

    assert events, "expected trace events but none were returned"

    types = {e.get("event_type") for e in events}
    assert "feedback_loop" in types
    assert "model_selection" not in types
    assert any(
        (event.get("payload") or {}).get("_schema_version") == "1.0"
        for event in events
        if event.get("event_type") == "feedback_loop"
    )
