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


def test_project_catalog_cold_start_edges():
    # Track B step 2: a history-less SKU becomes reachable through its catalog brand edge
    from src.app.services.hippograph import HippoGraph, project_catalog, recall
    g = HippoGraph()
    rows = [{"sku": "NEW-1", "name": "Asus Fresh 16 Laptop"},
            {"sku": "NEW-2", "name": "Asus Other 14 Laptop"},
            {"sku": "NEW-3", "name": "NoBrandThing 500ml"}]
    project_catalog(g, rows, alias_map={"asus": "asus"}, known=["asus"])
    assert "NEW-1" in g.nodes and g.nodes["NEW-1"].kind == "product"
    assert any(n.kind == "brand" for n in g.nodes.values())
    out = dict(recall(g, ["NEW-1"], top_k=5))
    assert any(nid == "NEW-2" for nid in out), "cold SKU must recall its brand sibling"
    # catalog edges are LOW weight (reachability, not reward)
    brand_id = next(nid for nid, n in g.nodes.items() if n.kind == "brand")
    assert g.edges[("NEW-1", brand_id)] <= 0.5


def test_mi_mode_env_wins(monkeypatch):
    # audit 2026-07-09: env never reached the stage flags -> mode silently off in every live run
    from src.app.services.recommend_intelligence_stage import _mi_mode
    monkeypatch.setenv("HIPPOGRAPH_FEEDBACK_ENABLED", "shadow")
    assert _mi_mode({}) == "shadow"
    monkeypatch.delenv("HIPPOGRAPH_FEEDBACK_ENABLED", raising=False)
    assert _mi_mode({"HIPPOGRAPH_FEEDBACK_ENABLED": "live"}) == "live"
    assert _mi_mode({}) == "off"
