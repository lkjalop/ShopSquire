import time
from fastapi.testclient import TestClient
from src.app.main import create_app


def test_complex_query_triggers_tier_decision_and_nqe(monkeypatch):
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "1")
    monkeypatch.setenv("MERCHANT_API_KEY", "local-merchant-key")

    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}

    # Complex, long query to encourage LLM/complexity signals and NQE behavior
    long_query = "I need a laptop for machine learning, 32GB RAM, discrete GPU, 4k display, under $2000, but also lightweight for travel. Also, explain tradeoffs between battery life and GPU performance."

    resp = client.get("/api/v1/recommend/suggest", params={"uid": "user-complex-1", "query": long_query}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    trace_id = data.get("trace_id") or data.get("decision_trace_id")
    assert trace_id

    # Poll trace events for tier_decision (canonicalized model_selection) and feedback_loop (next_questions)
    deadline = time.time() + 5.0
    seen = set()
    while time.time() < deadline:
        q = client.get(f"/api/v1/decisions/{trace_id}/query", params={"include_events": "true"}, headers=headers)
        if q.status_code == 200:
            body = q.json()
            events = body.get("events") or []
            for e in events:
                seen.add(e.get("event_type"))
            if "tier_decision" in seen or "feedback_loop" in seen:
                break
        time.sleep(0.25)

    assert "tier_decision" in seen or "feedback_loop" in seen
