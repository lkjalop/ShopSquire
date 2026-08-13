from src.app.services.hippograph import HippoGraph, HippoNode
from src.app.services.hippograph_journey_projection import project_hippograph_journey


def _connect(graph: HippoGraph, source: str, target: str, *, kind: str) -> None:
    graph.edges[(source, target)] = 1.0
    graph.adjacency.setdefault(source, {})[target] = 1.0
    graph.adjacency.setdefault(target, {})[source] = 0.5
    graph.edge_kinds[(source, target)] = {kind: 1.0}
    graph.edge_evidence[(source, target)] = [{
        "evidence_id": f"ev-{target}",
        "source_authority": "authoritative",
        "observed_at": "2026-08-13T00:00:00Z",
    }]


def test_projects_buyer_to_market_lanes_without_action_authority() -> None:
    graph = HippoGraph(nodes={
        "shopping_case:1": HippoNode("shopping_case:1", "shopping_case", "case 1"),
        "requirement:ram": HippoNode("requirement:ram", "requirement", "RAM >= 32 GB"),
        "LAP-1": HippoNode("LAP-1", "product", "Mobile workstation", weight=0.8),
        "supplier:s1": HippoNode("supplier:s1", "supplier", "Supplier One"),
        "finding:demand": HippoNode("finding:demand", "finding", "Demand rising", weight=0.6),
        "decision:d1": HippoNode("decision:d1", "decision", "Buyer confirmed"),
    })
    for target, kind in (
        ("requirement:ram", "research_context"),
        ("LAP-1", "qualified_candidate"),
        ("supplier:s1", "sourced_from"),
        ("finding:demand", "market_signal"),
        ("decision:d1", "buyer_confirmed"),
    ):
        _connect(graph, "shopping_case:1", target, kind=kind)

    view = project_hippograph_journey(graph, ["shopping_case:1"])

    assert view.authority == "evidence_only"
    assert view.ranking_authority == "none"
    assert view.commerce_authority == "none"
    by_lane = {lane.lane: lane for lane in view.lanes}
    assert by_lane["research_evidence"].entities[0].entity_id == "requirement:ram"
    assert by_lane["catalog_and_fit"].entities[0].outcome_prior == 0.8
    assert by_lane["inventory_and_procurement"].entities[0].entity_id == "supplier:s1"
    assert by_lane["sales_and_market"].entities[0].entity_id == "finding:demand"
    assert by_lane["outcome_and_governance"].entities[0].entity_id == "decision:d1"
    assert all(entity.evidence_path.authority == "evidence_only" for lane in view.lanes for entity in lane.entities)


def test_degraded_sources_remain_visible_and_empty_lanes_are_stable() -> None:
    graph = HippoGraph(
        nodes={"shopping_case:1": HippoNode("shopping_case:1", "shopping_case", "case 1")},
        degraded_sources=[{"source": "publisher-x", "health": "degraded", "reason": "timeout"}],
    )

    view = project_hippograph_journey(graph, ["shopping_case:1"])

    assert len(view.lanes) == 6
    assert all(lane.entities == [] for lane in view.lanes)
    assert view.degraded_sources == [{
        "source": "publisher-x", "health": "degraded", "reason": "timeout",
    }]


def test_unreachable_seed_does_not_create_false_graph_evidence() -> None:
    view = project_hippograph_journey(HippoGraph(), ["unknown-case"])
    assert view.seed_ids == ["unknown-case"]
    assert view.node_kind_counts == {}
    assert all(not lane.entities for lane in view.lanes)
