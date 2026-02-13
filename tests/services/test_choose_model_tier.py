"""Unit tests for Orchestrator.choose_model_tier and proposal metadata persistence.

These tests validate tier selection heuristics and ensure proposal includes
llm_model, text_tier, and vision_tier fields.
"""

import pytest

from typing import Any, Dict

from src.app.services.orchestrator import Orchestrator


class DummyMemory:
    def get_context(self, uid: str) -> Dict[str, Any]:
        return {"kv": {}}

    def set_recent_retrieval(self, uid: str, live: Dict[str, Any]) -> None:
        pass


class DummyFirewall:
    def check_pricing(self, cart_total_cents: int, proposed_discount_percent: int):
        class Result:
            allowed = True
            approval_required = False
            reason = "ok"
            escalation_role = None
            policy_version = "v1"
        return Result()

    def idempotency_ok(self, exists: bool):
        return (not exists, "ok")


@pytest.fixture
def orchestrator():
    flags = {
        "MODEL_T1": "glm4-mini",
        "MODEL_T2": "glm4-base",
        "MODEL_T3": "glm4-pro",
        "POLICY_VERSION": "v1",
        "DECISION_LOG_WRITES_ENABLED": False,
    }
    return Orchestrator(memory=DummyMemory(), firewall=DummyFirewall(), flags=flags)


data_cases = [
    # No images, normal confidence/amount → T1
    ({"images": None, "intent_confidence": 0.95, "amount": 99.0}, "T1"),
    # Low confidence or multi-turn → T2
    ({"images": None, "intent_confidence": 0.6, "amount": 99.0}, "T2"),
    ({"images": None, "intent_confidence": 0.9, "multi_turn": True, "amount": 99.0}, "T2"),
    # High risk or high amount → T3
    ({"images": None, "intent_confidence": 0.9, "amount": 300.0}, "T3"),
]


@pytest.mark.parametrize("payload,expected_tier", data_cases)
def test_choose_model_tier(orchestrator: Orchestrator, payload: Dict[str, Any], expected_tier: str):
    retrieved = {"live": {}}
    sec = {"risk_adj": 0.0}
    spec = orchestrator.choose_model_tier(payload, retrieved, sec)
    assert spec["text_tier"] == expected_tier
    # Vision tier only set when images present
    if payload.get("images"):
        assert spec["vision_tier"] in ("V1", "V2")
    else:
        assert spec["vision_tier"] in ("N/A", "V0")


def test_run_includes_tier_metadata(orchestrator: Orchestrator):
    # Simulate payload with image URLs and moderate amount
    payload = {
        "cart_total_cents": 15000,
        "image_urls": ["https://example.com/test.jpg"],
        "intent_confidence": 0.8,
        "multi_turn": False,
        "amount": 150.0,
        "idempotency_key": "unit-test-key-1",
    }
    result = orchestrator.run(uid="u123", payload=payload, simulate_only=True)
    proposal = result.proposal
    # Validate presence of metadata
    assert "llm_model" in proposal
    assert "text_tier" in proposal
    assert "vision_tier" in proposal
    # Validate reasonable tier values
    assert proposal["text_tier"] in ("T1", "T2", "T3")
    assert proposal["vision_tier"] in ("N/A", "V0", "V1", "V2")
