from __future__ import annotations

from typing import Dict, Any, List

from src.app.analytics.graph_builder import build_graph


def score_graph_risk(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    graph = build_graph(events)
    ring_count = graph.get("ring_candidate_count", 0)
    risk_band = "low"
    if ring_count >= 10:
        risk_band = "high"
    elif ring_count >= 4:
        risk_band = "medium"
    return {
        "graph": graph,
        "ring_candidates": ring_count,
        "risk_band": risk_band,
    }
