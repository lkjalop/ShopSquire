from datetime import datetime, timezone

from src.app.services.hippograph_journey_edges import TypedJourneyEdge
from src.app.services.hippograph_view_selector import (
    MemoryQueryPurpose,
    select_graph_view,
    traverse_journey_view,
)


def _edge(edge_id, source, source_kind, target, target_kind, relation):
    return TypedJourneyEdge(
        edge_id=edge_id, tenant_id="portfolio", source_id=source, source_kind=source_kind,
        target_id=target, target_kind=target_kind, relation=relation,
        signal_class="observed", evidence_id=f"evidence-{edge_id}",
        observed_at="2026-08-17T00:00:00+00:00",
        effective_at="2026-08-17T00:00:00+00:00",
    )


def test_supplier_question_does_not_traverse_post_purchase_outcomes():
    edges = [
        _edge("offer", "configuration:a", "configuration", "offer:a", "supplier_offer", "has_supplier_offer"),
        _edge("option", "offer:a", "supplier_offer", "option:a", "fulfillment_option", "offers_fulfillment_option"),
        _edge("select", "option:a", "fulfillment_option", "decision:a", "buyer_decision", "selected_by_buyer"),
        _edge("outcome", "decision:a", "buyer_decision", "order:a", "order_outcome", "produced_order_outcome"),
    ]
    receipt = traverse_journey_view(
        edges, start_node_ids=("configuration:a",),
        plan=select_graph_view(MemoryQueryPurpose.SUPPLIER_FULFILMENT),
    )
    assert receipt.selected_edge_ids == ("offer", "option", "select")
    assert "outcome" not in receipt.selected_edge_ids


def test_traversal_is_bounded_and_reports_truncation():
    edges = [
        _edge(f"e{index}", f"configuration:{index}", "configuration",
              f"configuration:{index + 1}", "availability_observation",
              "has_availability_observation")
        for index in range(6)
    ]
    receipt = traverse_journey_view(
        edges, start_node_ids=("configuration:0",),
        plan=select_graph_view(MemoryQueryPurpose.PRODUCT_FIT, max_depth=2),
    )
    assert receipt.selected_edge_ids == ("e0", "e1")
    assert receipt.truncated is True


def test_historical_view_never_leaks_evidence_observed_later():
    edge = _edge(
        "future-observation", "configuration:a", "configuration",
        "availability:a", "availability_observation", "has_availability_observation",
    ).model_copy(update={"observed_at": "2026-08-20T00:00:00+00:00"})
    receipt = traverse_journey_view(
        [edge], start_node_ids=("configuration:a",),
        plan=select_graph_view(MemoryQueryPurpose.HISTORICAL_KNOWLEDGE),
        knowledge_cutoff=datetime(2026, 8, 17, tzinfo=timezone.utc),
        evaluation_time=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    assert receipt.selected_edge_ids == ()
    assert receipt.not_yet_known_edge_ids == ("future-observation",)


def test_sqlite_style_naive_edge_timestamps_are_interpreted_as_utc():
    edge = _edge(
        "naive-observation", "configuration:a", "configuration",
        "availability:a", "availability_observation", "has_availability_observation",
    ).model_copy(update={
        "observed_at": "2026-08-17T01:00:00",
        "effective_at": "2026-08-17T01:00:00",
    })
    receipt = traverse_journey_view(
        [edge], start_node_ids=("configuration:a",),
        plan=select_graph_view(MemoryQueryPurpose.PRODUCT_FIT),
        knowledge_cutoff=datetime(2026, 8, 17, 2, tzinfo=timezone.utc),
        evaluation_time=datetime(2026, 8, 17, 2, tzinfo=timezone.utc),
    )
    assert receipt.selected_edge_ids == ("naive-observation",)
