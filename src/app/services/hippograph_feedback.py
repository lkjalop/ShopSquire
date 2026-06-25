"""Hippograph feedback injection (agnostic CORE, advisory-OFF).

Builds the reward-weighted recall of entities related to the current turn — seeded from the
session's uid + the SKUs it surfaced (and optionally brands) — so agents/dashboards can READ what
the graph knows about this context. ADVISORY-ONLY and flag-gated (HIPPOGRAPH_FEEDBACK_ENABLED,
default off) until benched: it never changes ranking or acts; it only annotates the response/session.
Any recalled entity that later drives an action re-enters policy → escalation → audit. Returns []
on any failure — never raises into the request path.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_hippograph_insights(
    db,
    *,
    uid_hash: Optional[str] = None,
    seed_skus: Optional[List[str]] = None,
    seed_brands: Optional[List[str]] = None,
    top_k: int = 8,
    limit: int = 2000,
) -> List[Dict[str, Any]]:
    """Reward-weighted entities related to this turn's seeds. Empty list when there's nothing to
    say (no graph, no seed in the graph) or on any error."""
    try:
        from src.app.services.hippograph import recall
        from src.app.services.hippograph_db import build_from_db

        graph = build_from_db(db, limit=limit)
        if not graph.nodes:
            return []
        seeds: List[str] = []
        if uid_hash:
            seeds.append(str(uid_hash))
        seeds.extend(str(s) for s in (seed_skus or []) if s)
        if seed_brands:
            from src.app.services.entity_resolution import resolve_brand_for_profile
            for b in seed_brands:
                ref = resolve_brand_for_profile(b)
                if ref:
                    seeds.append(ref.id)
        seeds = [s for s in seeds if s in graph.nodes]  # only seeds the graph actually knows
        if not seeds:
            return []
        out: List[Dict[str, Any]] = []
        for nid, score in recall(graph, seeds, top_k=top_k):
            node = graph.nodes.get(nid)
            out.append({
                "id": nid,
                "kind": node.kind if node else None,
                "label": node.label if node else nid,
                "score": round(float(score), 4),
                "reward_weight": round(float(node.weight), 2) if node else 0.0,
            })
        return out
    except Exception:
        return []
