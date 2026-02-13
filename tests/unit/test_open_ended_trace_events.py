import os
import time
from fastapi.testclient import TestClient


def test_open_ended_emits_model_selection_and_next_questions(monkeypatch):
    # Tame heavy middlewares and tolerate GET errors for test stability
    os.environ["TEST_TOLERANT_GET_ERRORS"] = "1"
    os.environ["DISABLE_SECURITY_MIDDLEWARE"] = "1"

    # Build app
    from src.app.main import create_app
    app = create_app()
    client = TestClient(app)

    # Force low intent confidence and no preferences to trigger open-ended path
    def _fake_analyze(self, q, prefs):
        return {"intent": "browse", "intent_confidence": 0.2, "preferences": {}}

    monkeypatch.setattr(
        "src.app.services.recommendations.RecommendationService.analyze_query",
        _fake_analyze,
    )

    # Execute suggest with an open-ended query
    r = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": "u-test", "query": "I need a laptop"},
        headers={"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")},
    )
    assert r.status_code == 200
    data = r.json()
    # Response should include next_questions
    nq = data.get("next_questions")
    assert isinstance(nq, list) and len(nq) >= 2
    # Model tier should be present (small/big)
    assert data.get("model_tier") in ("small", "big")
    trace_id = data.get("trace_id")
    assert trace_id, "trace_id missing in response"

    # Poll query endpoint for trace events with a bounded wait.
    events = []
    for _ in range(10):
        q = client.get(
            f"/api/v1/decisions/{trace_id}/query",
            params={"include_events": "true"},
            headers={"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")},
        )
        if q.status_code == 200:
            ev = q.json().get("events")
            if isinstance(ev, list) and ev:
                events = ev
                break
        time.sleep(0.25)
    assert events, "Trace events missing after bounded poll"
    types = [e.get("event_type") for e in events]
    # Canonicalization may map model_selection -> tier_decision and
    # next_questions -> feedback_loop.
    assert ("model_selection" in types or "tier_decision" in types), f"model selection event missing; types={types}"
    assert ("next_questions" in types or "feedback_loop" in types), f"next questions event missing; types={types}"
