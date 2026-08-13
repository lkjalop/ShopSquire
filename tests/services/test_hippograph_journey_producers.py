from types import SimpleNamespace

from src.app.services.hippograph_journey_producers import (
    accepted_requirement_edges, cart_outcome_edge, fulfillment_selection_edges,
)


def test_accepted_claims_emit_accepted_requirement_capability_edges():
    edges = accepted_requirement_edges(
        tenant_id="t1", case_id="sc-1", proposal_id="rp-1",
        claims=[{"claim_id": "c1", "attribute": "ram_gb", "operator": ">=", "value": 32}],
        observed_at="2026-08-13T00:00:00Z",
    )
    assert len(edges) == 1
    assert edges[0].signal_class == "accepted"
    assert edges[0].relation == "requires_capability"
    assert edges[0].attributes["value"] == 32


def test_fulfillment_emits_offer_option_decision_and_cart_outcome():
    offer = SimpleNamespace(
        offer_id="offer-1", offered_sku="SKU-1", quantity_available=18,
        lead_time_days=8, trust_status="trusted", response_status="accepted",
        provenance={"supplier_reference": "supplier-a"},
    )
    selection = SimpleNamespace(
        selection_id="fs-1", choice="split_delivery", requested_quantity=30,
        offers=[offer], cart_plan_id="plan-1",
    )
    edges = fulfillment_selection_edges(
        tenant_id="t1", case_id="sc-1", selection=selection,
        observed_at="2026-08-13T00:00:00Z",
    )
    assert [edge.signal_class.value for edge in edges] == ["attested", "derived", "accepted"]
    assert [edge.relation.value for edge in edges] == [
        "has_supplier_offer", "offers_fulfillment_option", "selected_by_buyer",
    ]
    outcome = cart_outcome_edge(
        tenant_id="t1", case_id="sc-1", selection=selection,
        cart_result={"status": "applied"}, observed_at="2026-08-13T00:00:01Z",
    )
    assert outcome.signal_class == "outcome"
    assert outcome.relation == "produced_order_outcome"
