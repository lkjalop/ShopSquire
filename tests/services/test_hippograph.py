"""Unit tests for hippograph projection + recall (services/hippograph.py).

Proves the two properties that make the latent graph useful: (1) entity canonicalization DEDUPES
nodes (brand variants collapse), and (2) conversion reward edges make high-converting entities
surface first in recall.
"""
from __future__ import annotations

from src.app.services.hippograph import project_graph, recall


def _trace(s_type, s_id, t_type, t_id):
    return {"source_type": s_type, "source_id": s_id, "target_type": t_type, "target_id": t_id}


def test_empty_inputs_empty_graph():
    g = project_graph([], [])
    assert g.nodes == {} and g.edges == {}
    assert recall(g, ["x"]) == []


def test_brand_variants_dedupe_to_one_node():
    rows = [
        _trace("user", "u1", "brand", "Dell"),
        _trace("user", "u2", "brand", "DELL"),
        _trace("user", "u3", "brand", "  dell "),
    ]
    g = project_graph(rows, [], known=["dell"])
    assert "dell" in g.nodes
    # exactly one brand node despite 3 spellings (the whole point of canonicalization)
    brand_nodes = [n for n in g.nodes.values() if n.kind == "brand"]
    assert len(brand_nodes) == 1


def test_edges_built_between_canonical_nodes():
    g = project_graph([_trace("user", "u1", "product", "GAM-1")], [], catalog_skus=["GAM-1"])
    assert ("u1", "GAM-1") in g.edges
    # reverse adjacency exists (half weight) so recall can traverse either way
    assert "u1" in g.adjacency.get("GAM-1", {})


def test_conversion_reward_boosts_product_weight():
    g = project_graph(
        [_trace("decision", "D1", "product", "GAM-1")],
        [{"decision_id": "D1", "attributed_skus": ["GAM-1"], "value_cents": 119900}],
        catalog_skus=["GAM-1"],
    )
    assert g.nodes["GAM-1"].weight > 0  # reward accumulated


def test_recall_returns_related_nodes():
    # u1 -> Dell, u1 -> GAM-1 ; seed from u1 should recall both neighbours
    rows = [_trace("user", "u1", "brand", "Dell"), _trace("user", "u1", "product", "GAM-1")]
    g = project_graph(rows, [], known=["dell"], catalog_skus=["GAM-1"])
    out = dict(recall(g, ["u1"], top_k=10))
    assert "dell" in out and "GAM-1" in out
    assert "u1" not in out  # seeds are excluded


def test_recall_reward_weighted_high_converter_first():
    # Two products both reachable from u1; GAM-HOT has reward, GAM-COLD doesn't.
    rows = [
        _trace("user", "u1", "product", "GAM-HOT"),
        _trace("user", "u1", "product", "GAM-COLD"),
    ]
    conv = [{"decision_id": "D1", "attributed_skus": ["GAM-HOT"], "value_cents": 500000}]
    g = project_graph(rows, conv, catalog_skus=["GAM-HOT", "GAM-COLD"])
    ranked = recall(g, ["u1"], top_k=10)
    order = [nid for nid, _ in ranked]
    assert order.index("GAM-HOT") < order.index("GAM-COLD"), f"reward should rank HOT first: {ranked}"


def test_recall_deterministic():
    rows = [_trace("user", "u1", "product", "P1"), _trace("user", "u1", "product", "P2")]
    g = project_graph(rows, [], catalog_skus=["P1", "P2"])
    assert recall(g, ["u1"]) == recall(g, ["u1"])  # stable ordering


# ── findings projection ──────────────────────────────────────────────────────
def test_project_findings_creates_finding_node_and_edge():
    from src.app.services.hippograph import project_findings
    g = project_graph([_trace("user", "u1", "product", "GAM-1")], [], catalog_skus=["GAM-1"])
    finding = {"finding_type": "inventory_demand_mismatch", "entity_ref": "GAM-1",
               "severity": "critical", "confidence": 0.9}
    project_findings(g, [finding], sku_pattern=r"[A-Za-z0-9][\w.\-]{0,63}")
    fid = "finding:inventory_demand_mismatch:GAM-1"
    assert fid in g.nodes and g.nodes[fid].kind == "finding"
    assert g.nodes[fid].weight > 0  # severity*confidence
    assert (fid, "GAM-1") in g.edges  # indicates edge to the entity


def test_recall_from_entity_surfaces_its_finding():
    from src.app.services.hippograph import project_findings
    g = project_graph([_trace("user", "u1", "product", "GAM-1")], [], catalog_skus=["GAM-1"])
    project_findings(g, [{"finding_type": "conversion_anomaly", "entity_ref": "GAM-1",
                          "severity": "warn", "confidence": 0.8}],
                     sku_pattern=r"[A-Za-z0-9][\w.\-]{0,63}")
    out = dict(recall(g, ["GAM-1"], top_k=10))
    assert "finding:conversion_anomaly:GAM-1" in out  # the finding is recalled from the entity


def test_project_findings_global_node_no_entity_edge():
    from src.app.services.hippograph import project_findings
    g = project_graph([], [])
    project_findings(g, [{"finding_type": "demand_shift", "entity_ref": None,
                          "severity": "info", "confidence": 0.5}])
    assert "finding:demand_shift:global" in g.nodes
    assert g.edges == {}  # global finding has no entity edge
