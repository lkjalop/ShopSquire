import json
import os
from tests.utils import default_headers

from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.services.recommendations import RecommendationService


app = create_app()

client = TestClient(app, headers=default_headers())


def _write_flags(flags: dict):
    path = os.path.join("config", "feature_flags.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_recommend_blocks_invalid_sku_output():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Product", "price_cents": 1000, "currency": "USD", "stock": 5}
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": True,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "test"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "blocked"
        assert body.get("approval_id")
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_rollout_not_eligible_rules_only():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Product", "price_cents": 1000, "currency": "USD", "stock": 5}
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 0,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 0}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "test"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("eligible") is False
        assert body.get("proposal", {}).get("decision_mode") == "rules"
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_bulk_quantity_insufficient_stock_creates_approval():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Product", "price_cents": 1000, "currency": "USD", "stock": 5}
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "need 10 laptops under $1500"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "review_required"
        assert body.get("approval_id")
        esc = body.get("escalation") or {}
        assert esc.get("reason") == "insufficient_stock_bulk"
        assert esc.get("approval_required") is True
        assert esc.get("approval_id") == body.get("approval_id")
        assert (esc.get("tags") or []).count("inventory_insufficient_stock") >= 1
        assert (esc.get("playbook_hint") or {}).get("id") == "PB-INV-004"
        trace_id = body.get("trace_id") or body.get("decision_trace_id")
        assert trace_id
        ev = client.get(f"/api/v1/trace/{trace_id}/events")
        assert ev.status_code == 200
        events = ev.json().get("events") or []
        assert any(
            e.get("event_type") == "handoff_requested"
            and e.get("source_id") == "Inventory_Agent"
            and e.get("target_id") == "Sales_Agent"
            for e in events
        )
        # Approval should show up in the pending queue.
        pend = client.get("/api/v1/approvals/pending")
        assert pend.status_code == 200
        pending = pend.json().get("pending") or []
        assert any(p.get("id") == body.get("approval_id") for p in pending)
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_redacts_pii_in_response_constraints_and_notices():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "SKU1", "name": "Test Laptop", "price_cents": 120000, "currency": "USD", "stock": 5}
        ]
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        q = "Need laptop around $1500 for alice@example.com and SSN 123-45-6789"
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": q})
        assert r.status_code == 200
        body = r.json()
        constraints = body.get("constraints_used") or {}
        q_used = str(constraints.get("query") or "")
        assert "[REDACTED_EMAIL]" in q_used
        assert ("[REDACTED_SSN]" in q_used) or ("[REDACTED_PHONE]" in q_used)
        assert "alice@example.com" not in q_used
        assert "123-45-6789" not in q_used
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve


def test_recommend_unsupported_product_category_returns_no_substitute():
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        def _fail_if_called(self, query, limit=10):
            raise AssertionError("retrieve_candidates should not be called for unsupported category")

        RecommendationService.retrieve_candidates = _fail_if_called
        _write_flags({
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False,
            "DECISION_LOG_WRITES_ENABLED": False,
            "DEGRADATION": {"enabled": True},
            "TEST_FORCE_BAD_SKU": False,
        })
        r = client.get("/api/v1/recommend/suggest", params={"uid": "u1", "query": "Need a kitchen mixer under $400"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "unsupported_request"
        assert body.get("results") == []
        esc = body.get("escalation") or {}
        assert esc.get("route") == "human_review"
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
