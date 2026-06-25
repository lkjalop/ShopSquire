"""Hippograph projection + recall (agnostic CORE, read-only).

Projects the graph that ALREADY exists latently — decision_trace_events is an edge table
(source→target labeled by event_type) and conversion_event holds reward edges — into an in-memory
graph whose nodes are CANONICAL entities (deduped via entity_resolution). It then recalls the top-k
related entities for a set of seed nodes via spreading activation (a Personalized-PageRank
approximation), reward-weighted so high-converting entities surface first.

READ-ONLY: never writes or executes. In-memory adapter first (proves the latent graph at zero
risk); a Neo4j-backed projection is a later swap when multi-hop becomes hot-path. The recalled
entities are *proposals* for agent context — they re-enter policy/escalation before they ever act.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.app.services.entity_resolution import resolve_brand, resolve_product, resolve_user


@dataclass
class HippoNode:
    id: str
    kind: str
    label: str
    weight: float = 0.0  # accumulated reward / activity prior


@dataclass
class HippoGraph:
    nodes: Dict[str, HippoNode] = field(default_factory=dict)
    edges: Dict[Tuple[str, str], float] = field(default_factory=dict)
    adjacency: Dict[str, Dict[str, float]] = field(default_factory=dict)


def _node_for(kind_hint: Any, raw_id: Any, *, alias_map, known, catalog_skus, sku_pattern=None) -> Optional[Tuple[str, str, str]]:
    """Map a (type, id) trace endpoint to a canonical (node_id, kind, label)."""
    k = str(kind_hint or "").strip().lower()
    if k == "product":
        ref = resolve_product(raw_id, sku_pattern=sku_pattern, catalog_skus=catalog_skus)
        return (ref.id, "product", ref.label) if ref else None
    if k == "brand":
        ref = resolve_brand(raw_id, alias_map=alias_map, known=known)
        return (ref.id, "brand", ref.label) if ref else None
    if k == "user":
        ref = resolve_user(raw_id, already_hashed=True)
        return (ref.id, "user", ref.label) if ref else None
    rid = str(raw_id or "").strip()
    if not rid:
        return None
    kind = k or "node"
    return (f"{kind}:{rid}", kind, rid)  # agent / decision / incident / etc.


def project_graph(
    trace_rows: Optional[Iterable[Dict[str, Any]]],
    conversion_rows: Optional[Iterable[Dict[str, Any]]] = None,
    *,
    alias_map: Optional[Dict[str, str]] = None,
    known: Optional[Iterable[str]] = None,
    catalog_skus: Optional[Iterable[str]] = None,
    sku_pattern: Optional[str] = None,
) -> HippoGraph:
    """Build the in-memory graph from trace edges + conversion reward edges.

    trace_rows: dicts with source_type/source_id/target_type/target_id (event_type optional).
    conversion_rows: dicts with decision_id, attributed_skus (list), value_cents.
    Pass ``catalog_skus`` (authoritative) or ``sku_pattern`` (permissive, for DB ids) so product
    ids stay canonical instead of being treated as free-text names.
    """
    g = HippoGraph()

    def ensure(nid: str, kind: str, label: str) -> HippoNode:
        n = g.nodes.get(nid)
        if n is None:
            n = HippoNode(nid, kind, label, 0.0)
            g.nodes[nid] = n
        return n

    def add_edge(s: str, d: str, w: float = 1.0) -> None:
        g.edges[(s, d)] = g.edges.get((s, d), 0.0) + w
        g.adjacency.setdefault(s, {})[d] = g.adjacency.setdefault(s, {}).get(d, 0.0) + w
        # half-weight reverse so recall can traverse either direction
        g.adjacency.setdefault(d, {})[s] = g.adjacency.setdefault(d, {}).get(s, 0.0) + w * 0.5

    for r in (trace_rows or []):
        s = _node_for(r.get("source_type"), r.get("source_id"), alias_map=alias_map, known=known, catalog_skus=catalog_skus, sku_pattern=sku_pattern)
        d = _node_for(r.get("target_type"), r.get("target_id"), alias_map=alias_map, known=known, catalog_skus=catalog_skus, sku_pattern=sku_pattern)
        if s:
            ensure(*s)
        if d:
            ensure(*d)
        if s and d:
            add_edge(s[0], d[0], 1.0)

    for c in (conversion_rows or []):
        val = (float(c.get("value_cents") or 0) / 100.0) or 1.0
        decision_id = str(c.get("decision_id") or "").strip()
        dn = f"decision:{decision_id}" if decision_id else None
        if dn:
            ensure(dn, "decision", decision_id)
        for sku in (c.get("attributed_skus") or []):
            ref = resolve_product(sku, sku_pattern=sku_pattern, catalog_skus=catalog_skus)
            if not ref:
                continue
            node = ensure(ref.id, "product", ref.label)
            node.weight += val  # the reward signal recall ranks toward
            if dn:
                add_edge(dn, ref.id, val)
    return g


def recall(
    graph: HippoGraph,
    seed_ids: Optional[Iterable[str]],
    *,
    top_k: int = 10,
    hops: int = 2,
    decay: float = 0.5,
) -> List[Tuple[str, float]]:
    """Spreading-activation recall (PPR approximation): from the seed nodes, spread activation across
    edges with per-hop decay, add each node's reward prior, drop the seeds, return the top-k
    (node_id, score). Deterministic: ties break by node id."""
    seedset = {str(s) for s in (seed_ids or [])}
    frontier: Dict[str, float] = {s: 1.0 for s in seedset if s in graph.nodes}
    scores: Dict[str, float] = {}
    visited = set(frontier)
    for hop in range(max(1, int(hops))):
        nxt: Dict[str, float] = {}
        for nid, act in frontier.items():
            for nb, w in (graph.adjacency.get(nid) or {}).items():
                contrib = act * w * (decay ** hop)
                scores[nb] = scores.get(nb, 0.0) + contrib
                if nb not in visited:
                    nxt[nb] = nxt.get(nb, 0.0) + contrib
        visited |= set(nxt)
        frontier = nxt
        if not frontier:
            break
    ranked: List[Tuple[str, float]] = []
    for nid, sc in scores.items():
        if nid in seedset:
            continue
        node = graph.nodes.get(nid)
        prior = node.weight if node else 0.0
        ranked.append((nid, sc + 0.1 * prior))
    ranked.sort(key=lambda x: (-x[1], x[0]))
    return ranked[: max(0, int(top_k))]
