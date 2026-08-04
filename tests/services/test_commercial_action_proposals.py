from datetime import datetime, timezone

from src.app.services.commercial_action_proposals import (
    propose_replenishment,
    propose_surplus_discount,
)


NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)


def _demand(source: str) -> dict:
    return {
        "scope": "this_item",
        "direction": "up",
        "confidence": 0.9,
        "observed_at": "2026-07-24T00:00:00Z",
        "source_system": source,
        "lineage_root": f"{source}/record-1",
        "provenance_chain": [f"{source}/record-1"],
        "tenant_id": "tenant-a",
        "sku": "SKU-1",
    }


def _atp() -> dict:
    return {
        "shortfall": 8,
        "lead_time_days": 12,
        "confidence": 0.95,
        "observed_at": "2026-07-24T00:00:00Z",
        "source_system": "wms",
        "provenance_chain": ["wms/snapshot-1"],
        "tenant_id": "tenant-a",
        "sku": "SKU-1",
    }


def _economics() -> dict:
    return {
        "available": True,
        "clears_floor": True,
        "cost_basis": "validated_landed_supplier_quote",
        "source_record_id": "quote-1",
        "provenance_chain": ["supplier/quote-1"],
        "tenant_id": "tenant-a",
        "sku": "SKU-1",
        "currency": "AUD",
    }


def test_surplus_discount_never_exceeds_headroom_or_applies_itself():
    proposal = propose_surplus_discount(
        sku="SKU-1",
        projection={"dead_stock": True, "dsi_days": 180},
        economics={
            "list_cents": 200_000,
            "wholesale_cents": 150_000,
            "discount_authorized": True,
            "cost_basis": "validated_landed_supplier_quote",
            "simulation_only": False,
        },
    )
    assert proposal["eligible"] is True
    assert 0 < proposal["recommended_discount_cents"] <= proposal["max_discount_cents"]
    assert proposal["human_gate"] == "required"
    assert proposal["auto_applied"] is False


def test_surplus_discount_fails_closed_for_demo_cost_or_below_floor():
    simulated = propose_surplus_discount(
        sku="SKU-1",
        projection={"dead_stock": True, "dsi_days": 180},
        economics={
            "list_cents": 200_000,
            "wholesale_cents": 150_000,
            "discount_authorized": False,
            "simulation_only": True,
        },
    )
    below_floor = propose_surplus_discount(
        sku="SKU-1",
        projection={"dead_stock": True, "dsi_days": 180},
        economics={
            "list_cents": 100_000,
            "wholesale_cents": 95_000,
            "discount_authorized": True,
            "simulation_only": False,
        },
    )
    assert simulated["eligible"] is False
    assert "unvalidated_landed_cost" in simulated["reasons"]
    assert below_floor["eligible"] is False
    assert below_floor["recommended_discount_cents"] == 0


def test_replenishment_proposal_preserves_policy_and_human_send_gate():
    proposal = propose_replenishment(
        sku="SKU-1",
        tenant_id="tenant-a",
        currency="AUD",
        demand_facts=[_demand("orders"), _demand("ga4")],
        atp=_atp(),
        economics=_economics(),
        now=NOW,
    )
    assert proposal["authorized"] is True
    assert proposal["send_gate"] == "human"
    assert proposal["auto_sent"] is False
    assert proposal["shortfall"] == 8


def test_replenishment_proposal_surfaces_denial_reasons():
    proposal = propose_replenishment(
        sku="SKU-1",
        tenant_id="tenant-a",
        currency="AUD",
        demand_facts=[_demand("orders")],
        atp={},
        economics={},
        now=NOW,
    )
    assert proposal["authorized"] is False
    assert "insufficient_independent_demand_sources" in proposal["reasons"]
    assert proposal["send_gate"] == "blocked"


def test_replenishment_does_not_count_mirrored_adapters_as_independent_demand():
    orders = _demand("orders")
    analytics = _demand("ga4")
    analytics["lineage_root"] = orders["lineage_root"]
    analytics["provenance_chain"] = [
        orders["lineage_root"],
        "ga4/mirrored-record-1",
    ]

    proposal = propose_replenishment(
        sku="SKU-1",
        tenant_id="tenant-a",
        currency="AUD",
        demand_facts=[orders, analytics],
        atp=_atp(),
        economics=_economics(),
        now=NOW,
    )

    assert proposal["authorized"] is False
    assert proposal["demand_source_count"] == 1
    assert "insufficient_independent_demand_sources" in proposal["reasons"]
