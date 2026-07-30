"""Async-narration handoff: /chat/query must forward the recommend layer's llm_summary_job_id (and a
summary_pending flag) so the storefront can poll /api/v1/recommend/narration/{job_id} and replace the
deterministic answer with the richer LLM prose in place. Without this the async narration is dropped."""
from fastapi.testclient import TestClient

from src.app.main import create_app


async def _fake_recommend(*args, **kwargs):
    """Recommend returned the deterministic answer plus an async narration job."""
    return 200, {
            "results": [{"sku": "GAM-0002", "name": "MSI Katana", "price_cents": 149900,
                         "specs": {"ram_gb": 16}, "factors": {"positive": ["+within_budget"]},
                         "score_norm": 90.0}],
            "assistant_message": "Deterministic grounded answer shown immediately.",
            "decision_trace_id": "trace-narr-1",
            "llm_summary_job_id": "job-narr-abc123",
            "summary_pending": True,
            "requested_quantity": 25,
            "bulk_budget": {"scope": "total", "total": 41000.0, "quantity": 25,
                            "per_unit_cap": 1640},
            "shelf": {"bands": [{"id": "closest_fit", "skus": ["GAM-0002"]}]},
            "capability": {"verdict": "below_budget"},
            "slate_disposition": "clear",
            "secondary_lanes": ["EXPLAIN"],
            "explanation": {"sku": "GAM-0002", "verdict": "fails"},
            "timing_breakdown": {
                "route_total_ms": 8123.4,
                "router_decode_ms": 7300.0,
                "fulfillment_preview_ms": 901.2,
            },
            "execution_mode": "v2_served",
            "execution_lane": "PROCUREMENT",
            "action_executed": False,
            "next_questions": [],
        }


def test_chat_query_forwards_narration_job_id(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router, "_call_recommend_in_process", _fake_recommend)
    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/chat/query",
        json={"uid": "u-chat-narr-1", "query": "10 work laptops $1300-$1500"},
        headers={"x-api-key": "local-merchant-key"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("llm_summary_job_id") == "job-narr-abc123"
    assert body.get("summary_pending") is True
    assert body.get("requested_quantity") == 25
    assert body.get("bulk_budget") == {"scope": "total", "total": 41000.0,
                                        "quantity": 25, "per_unit_cap": 1640}
    assert body["shelf"]["bands"][0]["id"] == "closest_fit"
    assert body["capability"]["verdict"] == "below_budget"
    assert body["slate_disposition"] == "clear"
    assert body["secondary_lanes"] == ["EXPLAIN"]
    assert body["explanation"]["verdict"] == "fails"
    assert body["timing_breakdown"] == {
        "route_total_ms": 8123.4,
        "router_decode_ms": 7300.0,
        "fulfillment_preview_ms": 901.2,
    }
    assert body["execution_mode"] == "v2_served"
    assert body["execution_lane"] == "PROCUREMENT"
    assert body["action_executed"] is False


async def _fake_no_match_with_brand_exclusion(*args, **kwargs):
    return 200, {
        "results": [],
        "assistant_message": "No exact in-catalog match right now.",
        "decision_trace_id": "trace-no-match",
        "next_questions": [],
        "confirmed_slots": {"brand_excludes": ["Apple"]},
        "turn_intent": "SEARCH",
    }


def test_no_match_followups_do_not_contradict_brand_exclusion(monkeypatch):
    from src.app.routers import chat as chat_router

    monkeypatch.setattr(chat_router, "_call_recommend_in_process",
                        _fake_no_match_with_brand_exclusion)
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/chat/query",
        json={"uid": "u-chat-no-apple", "query": "game development laptops, no Apple"},
        headers={"x-api-key": "local-merchant-key"},
    )

    assert response.status_code == 200
    questions = response.json().get("next_questions") or []
    assert "relax_brand" not in {question.get("id") for question in questions}
    assert all("Apple" not in str(question.get("text") or "") for question in questions)


async def _fake_policy_answer(*args, **kwargs):
    return 200, {
        "results": [],
        "assistant_message": "Approved returns policy.",
        "decision_trace_id": "trace-policy-v2",
        # The policy fast path may omit the generic lane field but always owns
        # this typed outcome.
        "policy_answered": True,
        "routing_source": "model",
        "next_questions": [],
    }


def test_chat_projects_authoritative_facade_lane(monkeypatch):
    from src.app.routers import chat as chat_router

    trace_events = []
    monkeypatch.setattr(chat_router, "_call_recommend_in_process", _fake_policy_answer)
    monkeypatch.setattr(
        chat_router,
        "log_trace_event",
        lambda **event: trace_events.append(event),
    )
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/chat/query",
        json={"uid": "u-chat-policy", "query": "What's your returns policy?"},
        headers={"x-api-key": "local-merchant-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["turn_intent"] == "POLICY_QUESTION"
    assert "returns" in body["assistant_message"].lower()
    assert body["next_questions"] == []
    assert body["needs_disambiguation"] is False
    finalized = [
        event for event in trace_events
        if event.get("event_type") == "intent_classify"
        and (event.get("payload") or {}).get("intent_authority")
        == "finalized_route"
    ]
    assert len(finalized) == 1
    assert finalized[0]["payload"]["intent_analysis"]["lane"] == "POLICY_QUESTION"


def test_authoritative_backend_lane_rejects_unknown_values():
    from src.app.routers import chat as chat_router

    assert chat_router._authoritative_backend_lane({"turn_intent": "search"}) == "SEARCH"
    assert chat_router._authoritative_backend_lane({"policy_answered": True}) == "POLICY_QUESTION"
    assert chat_router._authoritative_backend_lane({"turn_intent": "invented_lane"}) is None
