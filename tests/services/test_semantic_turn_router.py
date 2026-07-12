"""Model-judged turn router — the clamp/fallback safety contract (no network; stub llm_fn)."""
from __future__ import annotations

import json
from src.app.services.semantic_turn_router import classify_turn, LANES, _clamp

_CAPS = {
    "sells": ["laptop", "monitor"],
    "does_not_offer": ["payment_plans", "financing"],
    "off_catalog_classes": [{"class": "datacenter_gpu_server", "label": "rack-mount servers"}],
}


def _stub(resp: dict):
    return lambda prompt, timeout: json.dumps(resp)


def test_valid_lane_clamps_through():
    d = _clamp(json.dumps({"lane": "SEARCH", "confidence": 0.9}), _CAPS)
    assert d and d.lane == "SEARCH"


def test_off_catalog_grounds_on_positive_sells_list():
    # list-free: OFF_CATALOG trusted when the model names a category NOT in `sells` (world knowledge,
    # no maintained negative list). A never-listed product (forklift) is caught.
    d = _clamp(json.dumps({"lane": "OFF_CATALOG", "requested_category": "forklift", "in_catalog": False}), _CAPS)
    assert d and d.lane == "OFF_CATALOG" and d.requested_category == "forklift"
    # a category the store DOES sell can never be refused → clamp to None (fall back to retrieval)
    assert _clamp(json.dumps({"lane": "OFF_CATALOG", "requested_category": "gaming laptop", "in_catalog": True}), _CAPS) is None
    assert _clamp(json.dumps({"lane": "OFF_CATALOG", "requested_category": "monitor", "in_catalog": False}), _CAPS) is None
    # OFF_CATALOG with no category named → not trustworthy → None
    assert _clamp(json.dumps({"lane": "OFF_CATALOG", "requested_category": None}), _CAPS) is None


def test_invalid_lane_falls_back():
    assert _clamp(json.dumps({"lane": "TOTALLY_INVENTED"}), _CAPS) is None
    assert _clamp("not json at all", _CAPS) is None
    assert _clamp(json.dumps({"no_lane": 1}), _CAPS) is None


def test_policy_topic_must_be_declared():
    d = _clamp(json.dumps({"lane": "POLICY_QUESTION", "policy_topic": "payment_plans"}), _CAPS)
    assert d and d.policy_topic == "payment_plans"
    d2 = _clamp(json.dumps({"lane": "POLICY_QUESTION", "policy_topic": "unicorn_leasing"}), _CAPS)
    assert d2 and d2.policy_topic is None  # invented topic dropped, lane kept


def test_classify_turn_uses_injected_fn_and_clamps(monkeypatch):
    import src.app.services.semantic_turn_router as mod
    monkeypatch.setattr(mod, "get_capabilities", lambda pid=None: _CAPS, raising=False)
    d = classify_turn("anything", profile_id="electronics",
                      llm_fn=_stub({"lane": "CART_MUTATE", "confidence": 0.8}))
    assert d and d.lane == "CART_MUTATE"


def test_llm_failure_returns_none_for_fallback():
    def _boom(prompt, timeout):
        raise RuntimeError("model down")
    assert classify_turn("x", llm_fn=_boom) is None  # → caller uses deterministic
    assert classify_turn("", llm_fn=_stub({"lane": "SEARCH"})) is None  # empty query


def test_all_lanes_are_upper_and_closed():
    assert all(l == l.upper() for l in LANES) and len(set(LANES)) == len(LANES)
