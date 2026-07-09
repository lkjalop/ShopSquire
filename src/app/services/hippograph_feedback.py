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

# Buyer-/analysis-facing entity kinds. Internal graph nodes (the current user, decision nodes,
# agents) are excluded from insights — they are graph plumbing, not evidence.
_USEFUL_KINDS = {"product", "brand", "finding", "segment"}


def build_hippograph_insights(
    db,
    *,
    uid_hash: Optional[str] = None,
    seed_skus: Optional[List[str]] = None,
    seed_brands: Optional[List[str]] = None,
    seed_terms: Optional[List[str]] = None,
    top_k: int = 8,
    limit: int = 2000,
    coldstart_stats: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Reward-weighted entities related to this turn's seeds. Includes M3 ``finding`` nodes so a
    market finding tied to a surfaced product (or a query term) recalls alongside it — query-scoped
    by the seeds, not a global dump. Empty list when there's nothing to say or on any error."""
    try:
        import os

        from src.app.services.hippograph import recall, resolve_product
        from src.app.services.hippograph_db import _DEFAULT_SKU_PATTERN, build_from_db

        # include_findings projects persisted M3 findings as `finding` nodes (fast — batch computes
        # them); finding↔entity edges make a finding reachable from its product/term seed.
        # Human-correction learning folds in signed recall priors — opt-in (changes recall ordering).
        _hf_on = str(os.getenv("HIPPOGRAPH_HUMAN_FEEDBACK_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
        graph = build_from_db(db, limit=limit, include_findings=True, include_human_feedback=_hf_on)
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
        # Query terms → canonical entity ids using the SAME sku_pattern the finding projection used
        # (build_from_db's default), so an entity-scoped finding named by a query token resolves to the
        # identical node id and is reachable. (Without the pattern a token resolves to a `name:` node
        # that never matches the finding's product node.) This is the query-scoping lever.
        for term in (seed_terms or []):
            if not term:
                continue
            ref = resolve_product(str(term), sku_pattern=_DEFAULT_SKU_PATTERN)
            if ref:
                seeds.append(ref.id)
        # COLD-START observability (Track B, 2026-07-09): a seed the graph doesn't know (a long-tail
        # SKU with no trace/conversion history) is silently dropped — the feature is DARKEST exactly
        # on the newest catalog. Record how many seeds survived so the darkness is MEASURABLE (the
        # prerequisite to the catalog-edge cold-start fix). Populated even when recall succeeds.
        _proposed = len(seeds)
        seeds = [s for s in seeds if s in graph.nodes]  # only seeds the graph actually knows
        if isinstance(coldstart_stats, dict):
            coldstart_stats.update({
                "seeds_proposed": _proposed, "seeds_in_graph": len(seeds),
                "graph_nodes": len(graph.nodes), "cold": bool(_proposed and not seeds),
            })
        if not seeds:
            return []
        out: List[Dict[str, Any]] = []
        # Over-fetch then keep only useful kinds, so internal nodes (decision/user/agent) don't crowd
        # out real product/market evidence (GPT-5.5: recall was returning a decision + the user node).
        for nid, score in recall(graph, seeds, top_k=max(top_k * 4, top_k)):
            node = graph.nodes.get(nid)
            if not node or node.kind not in _USEFUL_KINDS:
                continue
            out.append({
                "id": nid,
                "kind": node.kind,
                "label": node.label,
                "score": round(float(score), 4),
                "reward_weight": round(float(node.weight), 2),
            })
            if len(out) >= top_k:
                break
        return out
    except Exception:
        return []
