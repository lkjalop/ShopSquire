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

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.app.services.entity_resolution import resolve_brand, resolve_product, resolve_user

logger = logging.getLogger("shopsquire.hippograph")


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
    # Evidence about why an edge exists. Recall still reads only bounded numeric
    # adjacency; consumers can inspect these typed contributions without treating
    # them as authorization or a ranking verdict.
    edge_kinds: Dict[Tuple[str, str], Dict[str, float]] = field(default_factory=dict)


_TRACE_EDGE_WEIGHTS = {
    "viewed": 0.15,
    "shortlisted": 0.35,
    "added_to_cart": 0.55,
    "purchased": 1.0,
    "returned": -0.8,
    "rejected": -0.6,
    "corrected": -0.35,
}


def _typed_edge(event_type: Any) -> Tuple[str, float]:
    raw = str(event_type or "observed").strip().lower()
    for kind, weight in _TRACE_EDGE_WEIGHTS.items():
        if kind in raw:
            return kind, weight
    return "observed", 0.1


def _bounded_conversion_reward(value_cents: Any) -> float:
    """Log-scale order value into [0.1, 1.0] so expensive products cannot dominate recall."""
    try:
        dollars = max(0.0, float(value_cents or 0) / 100.0)
    except (TypeError, ValueError):
        dollars = 0.0
    return max(0.1, min(1.0, math.log1p(dollars) / math.log1p(10000.0)))


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

    def add_edge(s: str, d: str, w: float = 1.0, kind: str = "observed") -> None:
        g.edges[(s, d)] = g.edges.get((s, d), 0.0) + w
        kinds = g.edge_kinds.setdefault((s, d), {})
        kinds[kind] = kinds.get(kind, 0.0) + w
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
            kind, weight = _typed_edge(r.get("event_type"))
            # Negative outcomes suppress the target prior but do not create a
            # negative traversal edge (spreading activation assumes non-negative
            # relatedness). The outcome remains visible in edge_kinds.
            if weight < 0:
                ensure(*d).weight += weight
                add_edge(s[0], d[0], abs(weight) * 0.25, kind)
            else:
                add_edge(s[0], d[0], weight, kind)

    for c in (conversion_rows or []):
        val = _bounded_conversion_reward(c.get("value_cents"))
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
                add_edge(dn, ref.id, val, "purchased")
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


_SEVERITY_WEIGHT = {"info": 0.3, "warn": 0.7, "critical": 1.0}


def _finding_attr(f: Any, name: str, default: Any = None) -> Any:
    return f.get(name, default) if isinstance(f, dict) else getattr(f, name, default)


def project_catalog(
    graph: HippoGraph,
    product_rows: Optional[Iterable[Dict[str, Any]]],
    *,
    alias_map: Optional[Dict[str, str]] = None,
    known: Optional[Iterable[str]] = None,
    edge_weight: float = 0.25,
) -> HippoGraph:
    """COLD-START seeding (Track B step 2, 2026-07-09): catalog-backed product↔brand edges.

    The trace/conversion projection only knows entities WITH HISTORY — a newly listed SKU is not
    a node at all, so recall was darkest exactly on the long-tail catalog (live diagnosis:
    seeds_proposed>0, seeds_in_graph=0 — current-catalog SKUs had zero history and no brand node
    bridged them to the 259 history nodes). The CATALOG is platform truth, so its product↔brand
    relation is legitimate graph structure: every active product becomes a node connected to its
    brand, and a cold seed now recalls brand siblings (including ones carrying findings/reward).

    ``edge_weight`` is deliberately LOW (0.25 vs 1.0 for history edges) so behavioral signal
    still dominates recall ordering — catalog edges provide REACHABILITY, not reward. Additive
    and read-only like every projection; never raises."""
    for row in (product_rows or []):
        try:
            sku = str((row.get("sku") if isinstance(row, dict) else row[0]) or "").strip()
            name = str((row.get("name") if isinstance(row, dict) else row[1]) or "").strip()
        except Exception as _e:   # malformed catalog row — skip it, but observably (ratchet)
            logger.debug("hippograph catalog-row skip: %s", repr(_e)[:100])
            continue
        if not sku:
            continue
        if sku not in graph.nodes:
            graph.nodes[sku] = HippoNode(id=sku, kind="product", label=name or sku)
        bref = resolve_brand(name, alias_map=alias_map, known=known) if name else None
        if not bref:
            continue
        if bref.id not in graph.nodes:
            graph.nodes[bref.id] = HippoNode(id=bref.id, kind="brand", label=bref.label)
        key = (sku, bref.id)
        graph.edges[key] = graph.edges.get(key, 0.0) + edge_weight
        graph.adjacency.setdefault(sku, {})[bref.id] = graph.adjacency.setdefault(sku, {}).get(bref.id, 0.0) + edge_weight
        graph.adjacency.setdefault(bref.id, {})[sku] = graph.adjacency.setdefault(bref.id, {}).get(sku, 0.0) + edge_weight * 0.5
    return graph


def project_findings(graph: HippoGraph, findings: Optional[Iterable[Any]], *, sku_pattern: Optional[str] = None) -> HippoGraph:
    """Add M3 findings as ``finding`` nodes (in place). Each finding becomes a node
    ``finding:<type>:<entity-or-global>`` whose weight is severity×confidence; when it names an
    entity, an ``indicates`` edge connects it to the (canonical) entity node so recall from that
    entity surfaces the finding. A negative finding (e.g. conversion drop) surfaces AS a finding
    without boosting the entity's own weight — the warning shows up, the entity isn't promoted.
    Accepts MarketFinding objects or dicts. Returns the same graph."""
    for f in (findings or []):
        ftype = str(_finding_attr(f, "finding_type") or "").strip()
        if not ftype:
            continue
        entity = _finding_attr(f, "entity_ref")
        severity = str(_finding_attr(f, "severity") or "info")
        confidence = float(_finding_attr(f, "confidence") or 0.0)
        weight = confidence * _SEVERITY_WEIGHT.get(severity, 0.5)
        ent_node: Optional[str] = None
        ent_key = "global"
        if entity:
            ref = resolve_product(str(entity), sku_pattern=sku_pattern)
            if ref:
                ent_node = ref.id
                ent_key = ref.id
        fid = f"finding:{ftype}:{ent_key}"
        node = graph.nodes.get(fid)
        if node is None:
            node = HippoNode(fid, "finding", f"{ftype} ({severity})", 0.0)
            graph.nodes[fid] = node
        node.weight += weight
        if ent_node:
            if ent_node not in graph.nodes:
                graph.nodes[ent_node] = HippoNode(ent_node, "product", str(entity), 0.0)
            w = max(0.5, weight)
            graph.edges[(fid, ent_node)] = graph.edges.get((fid, ent_node), 0.0) + w
            graph.adjacency.setdefault(fid, {})[ent_node] = graph.adjacency.setdefault(fid, {}).get(ent_node, 0.0) + w
            graph.adjacency.setdefault(ent_node, {})[fid] = graph.adjacency.setdefault(ent_node, {}).get(fid, 0.0) + w
    return graph


def project_human_feedback(graph: HippoGraph, feedback: Optional[Iterable[Any]], *,
                           sku_pattern: Optional[str] = None) -> HippoGraph:
    """Add human-in-the-loop feedback as a SIGNED learning signal (in place). For each row, the
    entity's recall PRIOR moves by polarity×weight — an approval/accepted recommendation lifts it, a
    rejection/return/escalation/finding-correction suppresses it (so the rejected entity ranks lower
    next time). The sign lives in the prior; CONNECTIVITY edges are always positive (relatedness, not
    judgement), keeping the spreading-activation math sound:
      • subject(user) → entity edge (|signed|) so the signal is personalized to who gave it,
      • a ``human:<feedback_type>`` node + edge for visibility/dashboards.
    Accepts HumanFeedback objects or dicts. Returns the same graph."""
    for f in (feedback or []):
        ftype = str(_finding_attr(f, "feedback_type") or "").strip()
        entity = _finding_attr(f, "entity_ref")
        etype = str(_finding_attr(f, "entity_type", "product") or "product")
        subject = _finding_attr(f, "subject_hash")
        polarity = float(_finding_attr(f, "polarity", 1.0) or 0.0)
        weight = float(_finding_attr(f, "weight", 1.0) or 0.0)
        signed = polarity * weight
        if not ftype or signed == 0.0:
            continue
        ent_node: Optional[str] = None
        if entity:
            # TYPED resolution: only a 'product' entity is resolved through the product resolver. A
            # decision/incident/attribute/campaign id becomes its OWN typed node (kind:id) — never a
            # fake product node (the bug: every entity_ref was resolved as a product).
            if etype == "product":
                ref = resolve_product(str(entity), sku_pattern=sku_pattern)
                if ref:
                    ent_node, ent_kind, ent_label = ref.id, "product", ref.label
                else:
                    ent_node = None
            else:
                ent_node, ent_kind, ent_label = f"{etype}:{entity}", etype, str(entity)
            if ent_node:
                node = graph.nodes.get(ent_node)
                if node is None:
                    node = HippoNode(ent_node, ent_kind, ent_label, 0.0)
                    graph.nodes[ent_node] = node
                node.weight += signed  # the human judgement tips the recall prior (can go negative)
        # visibility node — what human signal touched this turn's context
        hid = f"human:{ftype}"
        if hid not in graph.nodes:
            graph.nodes[hid] = HippoNode(hid, "feedback", ftype, 0.0)
        mag = abs(signed)
        if ent_node:
            graph.edges[(hid, ent_node)] = graph.edges.get((hid, ent_node), 0.0) + mag
            graph.adjacency.setdefault(hid, {})[ent_node] = graph.adjacency.setdefault(hid, {}).get(ent_node, 0.0) + mag
            graph.adjacency.setdefault(ent_node, {})[hid] = graph.adjacency.setdefault(ent_node, {}).get(hid, 0.0) + mag
        if subject and ent_node:
            sid = str(subject)
            if sid not in graph.nodes:
                graph.nodes[sid] = HippoNode(sid, "user", sid, 0.0)
            graph.adjacency.setdefault(sid, {})[ent_node] = graph.adjacency.setdefault(sid, {}).get(ent_node, 0.0) + mag
            graph.adjacency.setdefault(ent_node, {})[sid] = graph.adjacency.setdefault(ent_node, {}).get(sid, 0.0) + mag
    return graph
