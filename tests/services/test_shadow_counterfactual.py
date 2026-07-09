"""Track B measurable-shadow — the counterfactual nudge benches would-be uplift without acting."""
from __future__ import annotations

import types

from src.app.services.recommend_intelligence_stage import _shadow_counterfactual


class _State:
    def __init__(self, payload):
        self.payload = payload
        self.trace_id = "t"
        self.decision_id = "d"


def _traceless(monkeypatch):
    import src.app.services.recommend_intelligence_stage as mod
    monkeypatch.setattr(mod, "log_trace_event", lambda *a, **k: None)
    monkeypatch.setattr(mod, "record_partial_failure", lambda *a, **k: None)


def test_counterfactual_measures_would_be_move_without_mutating(monkeypatch):
    _traceless(monkeypatch)
    results = [
        {"sku": "A", "score": 0.9}, {"sku": "B", "score": 0.8}, {"sku": "C", "score": 0.7},
    ]
    before = [dict(r) for r in results]
    payload = {"hippograph_insights_shadow": [{"kind": "product", "id": "C", "score": 0.95}]}
    state = _State(payload)
    _shadow_counterfactual(state, results)
    # results untouched — shadow never mutates the buyer view
    assert results == before
    cf = payload["hippograph_shadow_counterfactual"]
    assert cf["recall_products"] == 1
    assert "C" in cf["would_boost"]
    assert cf["in_result_set"] == 1
    assert cf["would_move_positions"] >= 0


def test_noop_without_shadow_insights(monkeypatch):
    _traceless(monkeypatch)
    state = _State({})
    _shadow_counterfactual(state, [{"sku": "A", "score": 1.0}])
    assert "hippograph_shadow_counterfactual" not in state.payload


def test_recall_not_in_result_set_records_zero_impact(monkeypatch):
    _traceless(monkeypatch)
    payload = {"hippograph_insights_shadow": [{"kind": "product", "id": "Z", "score": 0.9}]}
    state = _State(payload)
    _shadow_counterfactual(state, [{"sku": "A", "score": 1.0}])
    cf = payload["hippograph_shadow_counterfactual"]
    assert cf["in_result_set"] == 0 and cf["would_move_positions"] == 0
