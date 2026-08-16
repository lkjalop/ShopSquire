import pytest

from src.app.services.hippograph import HippoGraph, explain_path
from src.app.services.hippograph_journey_edges import (
    GraphSignalClass,
    TypedJourneyEdge,
    project_typed_journey_edges,
)


def _edge(edge_id: str, source: str, source_kind: str, target: str, target_kind: str,
          relation: str, signal: str, when: str = "2026-08-01T00:00:00Z", **extra):
    return {
        "edge_id": edge_id, "tenant_id": "t1", "source_id": source,
        "source_kind": source_kind, "target_id": target, "target_kind": target_kind,
        "relation": relation, "signal_class": signal, "evidence_id": f"ev-{edge_id}",
        "observed_at": when, "effective_at": when, **extra,
    }


def test_projects_complete_requirement_to_outcome_chain_with_signal_classes():
    rows = [
        _edge("e1", "req:ram", "requirement", "cap:ram64", "capability", "requires_capability", "attested"),
        _edge("e2", "cfg:1", "configuration", "avail:1", "availability_observation", "has_availability_observation", "observed"),
        _edge("e3", "cfg:1", "configuration", "offer:1", "supplier_offer", "has_supplier_offer", "attested"),
        _edge("e4", "offer:1", "supplier_offer", "option:split", "fulfillment_option", "offers_fulfillment_option", "derived"),
        _edge("e5", "option:split", "fulfillment_option", "decision:1", "buyer_decision", "selected_by_buyer", "accepted"),
        _edge("e6", "decision:1", "buyer_decision", "order:1", "order_outcome", "produced_order_outcome", "outcome"),
        _edge("e7", "order:1", "order_outcome", "satisfaction:1", "satisfaction", "has_post_order_outcome", "outcome"),
    ]
    graph = HippoGraph()
    receipt = project_typed_journey_edges(graph, rows, tenant_id="t1", as_of="2026-08-02T00:00:00Z")

    assert receipt.projected_edge_ids == [f"e{i}" for i in range(1, 8)]
    path = explain_path(graph, ["req:ram"], "cap:ram64")
    assert path["hops"] == 2
    assert path["edges"][0]["evidence"][0]["signal_class"] == GraphSignalClass.ATTESTED
    assert explain_path(graph, ["decision:1"], "order:1")["edges"][0]["evidence"][0]["signal_class"] == "outcome"


def test_temporal_replay_excludes_future_and_uses_edge_visible_at_cutoff():
    old = _edge("old", "cfg:1", "configuration", "avail:old", "availability_observation",
                "has_availability_observation", "observed", when="2026-07-01T00:00:00Z")
    new = _edge("new", "cfg:1", "configuration", "avail:new", "availability_observation",
                "has_availability_observation", "observed", when="2026-08-01T00:00:00Z",
                supersedes_edge_id="old")

    july = HippoGraph()
    july_receipt = project_typed_journey_edges(
        july, [old, new], tenant_id="t1", as_of="2026-07-15T00:00:00Z",
    )
    assert july_receipt.projected_edge_ids == ["old"]
    assert july_receipt.future_edge_ids == ["new"]
    assert july_receipt.not_yet_known_edge_ids == ["new"]
    assert july_receipt.known_future_edge_ids == []
    assert "avail:old" in july.nodes and "avail:new" not in july.nodes

    august = HippoGraph()
    august_receipt = project_typed_journey_edges(
        august, [old, new], tenant_id="t1", as_of="2026-08-02T00:00:00Z",
    )
    assert august_receipt.projected_edge_ids == ["new"]
    assert august_receipt.inactive_edge_ids == ["old"]
    assert august_receipt.supersession_links == 1
    assert ("evidence:new", "evidence:old") in august.edges


def test_known_future_supplier_change_is_available_to_a_future_promise_without_leaking_history():
    delay = _edge(
        "delay", "offer:1", "supplier_offer", "option:late", "fulfillment_option",
        "offers_fulfillment_option", "attested",
        when="2026-08-16T09:00:00Z",
        effective_at="2026-08-18T00:00:00Z",
    )

    current_graph = HippoGraph()
    current = project_typed_journey_edges(
        current_graph, [delay], tenant_id="t1",
        knowledge_cutoff="2026-08-16T12:00:00Z",
        evaluation_time="2026-08-16T12:00:00Z",
    )
    assert current.known_future_edge_ids == ["delay"]
    assert current.not_yet_known_edge_ids == []
    assert current.projected_edge_ids == []

    promise_graph = HippoGraph()
    promise = project_typed_journey_edges(
        promise_graph, [delay], tenant_id="t1",
        knowledge_cutoff="2026-08-16T12:00:00Z",
        evaluation_time="2026-08-20T00:00:00Z",
    )
    assert promise.projected_edge_ids == ["delay"]

    historical_graph = HippoGraph()
    historical = project_typed_journey_edges(
        historical_graph, [delay], tenant_id="t1",
        knowledge_cutoff="2026-08-15T00:00:00Z",
        evaluation_time="2026-08-20T00:00:00Z",
    )
    assert historical.not_yet_known_edge_ids == ["delay"]
    assert historical.projected_edge_ids == []


def test_contradictions_are_explicit_and_do_not_delete_either_observation():
    first = _edge("a", "cfg:1", "configuration", "avail:a", "availability_observation",
                  "has_availability_observation", "observed")
    second = _edge("b", "cfg:1", "configuration", "avail:b", "availability_observation",
                   "has_availability_observation", "attested", contradicts_edge_ids=["a"])
    graph = HippoGraph()
    receipt = project_typed_journey_edges(graph, [first, second], tenant_id="t1")
    assert receipt.contradiction_links == 1
    assert set(receipt.projected_edge_ids) == {"a", "b"}
    assert graph.edge_kinds[("evidence:b", "evidence:a")] == {"contradicts": 0.1}


def test_kind_pair_and_tenant_scope_fail_closed():
    with pytest.raises(ValueError, match="invalid_kind_pair"):
        TypedJourneyEdge.model_validate(_edge(
            "bad", "req:1", "requirement", "supplier:1", "supplier_offer",
            "requires_capability", "inferred",
        ))
    graph = HippoGraph()
    row = _edge("other", "cfg:1", "configuration", "avail:1", "availability_observation",
                "has_availability_observation", "observed")
    row["tenant_id"] = "other"
    receipt = project_typed_journey_edges(graph, [row], tenant_id="t1")
    assert receipt.projected_edge_ids == [] and graph.nodes == {}
