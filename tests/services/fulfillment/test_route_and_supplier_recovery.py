from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.fulfillment.route_policy import (
    evaluate_fulfillment_route,
    normalize_supplier_schedule,
    persist_route_proposal,
)


def test_supplier_direct_requires_explicit_pii_authorization():
    blocked = evaluate_fulfillment_route(
        requested_mode="supplier_direct", policy_modes={"supplier_direct"},
        dispatch_days=(1, 2), transit_days=(2, 4), inspection_days=(0, 0),
        final_mile_days=(1, 1), buyer_destination={"name": "Ada", "address": "1 Main St"},
        destination_token="DEST-42", pii_release_authorized=False,
    )
    allowed = evaluate_fulfillment_route(
        requested_mode="supplier_direct", policy_modes={"supplier_direct"},
        dispatch_days=(1, 2), transit_days=(2, 4), inspection_days=(0, 0),
        final_mile_days=(1, 1), buyer_destination={"name": "Ada", "address": "1 Main St"},
        destination_token="DEST-42", pii_release_authorized=True,
    )

    assert blocked["status"] == "blocked" and blocked["state_prevented"] == "buyer_pii_release"
    assert blocked["supplier_destination"] == {"destination_token": "DEST-42"}
    assert allowed["status"] == "eligible"
    assert allowed["supplier_destination"]["address"] == "1 Main St"


def test_merchant_inspection_includes_capacity_and_full_eta_range():
    result = evaluate_fulfillment_route(
        requested_mode="merchant_inspected", policy_modes={"merchant_inspected", "cross_dock"},
        dispatch_days=(1, 2), transit_days=(3, 5), inspection_days=(2, 4),
        final_mile_days=(1, 2), warehouse_capacity_available=True,
        buyer_destination={"address": "private"}, destination_token="DEST-1",
    )
    no_capacity = evaluate_fulfillment_route(
        requested_mode="merchant_inspected", policy_modes={"merchant_inspected"},
        dispatch_days=(1, 2), transit_days=(3, 5), inspection_days=(2, 4),
        final_mile_days=(1, 2), warehouse_capacity_available=False,
        buyer_destination={"address": "private"}, destination_token="DEST-1",
    )

    assert result["eta_days"] == {"min": 7, "max": 13}
    assert result["supplier_destination"] == {"destination_token": "DEST-1"}
    assert no_capacity["status"] == "blocked"
    assert no_capacity["state_prevented"] == "inspection_capacity_unavailable"


def test_stale_supplier_inventory_is_unknown_not_confirmed():
    outcome = normalize_supplier_schedule(
        requested_qty=20,
        internal_allocated_qty=4,
        schedule_lines=[{"status": "confirmed", "quantity": 16, "eta": "2026-08-10"}],
        evidence_fresh=False,
    )

    assert outcome["supplier_confirmed_qty"] == 0
    assert outcome["supplier_state"] == "unknown_stale"
    assert outcome["promise_state"] == "unconfirmed"
    assert outcome["alternatives_required"] is True


def test_partial_and_rejected_supplier_lines_recompute_truthful_buyer_promise():
    partial = normalize_supplier_schedule(
        requested_qty=20, internal_allocated_qty=4,
        schedule_lines=[
            {"status": "confirmed", "quantity": 8, "eta": "2026-08-10"},
            {"status": "backordered", "quantity": 5, "eta": "2026-08-20"},
            {"status": "rejected", "quantity": 3},
        ], evidence_fresh=True,
    )

    assert partial["covered_qty"] == 12
    assert partial["shortfall_qty"] == 8
    assert partial["promise_state"] == "partial"
    assert partial["alternatives_required"] is True
    assert "12 of 20" in partial["buyer_message"]
    assert "confirmed" not in partial["buyer_message"].lower() or "12" in partial["buyer_message"]


def test_route_proposal_persists_eta_components_and_is_idempotent():
    db = sessionmaker(bind=create_engine("sqlite://"))()
    db.execute(text("""CREATE TABLE fulfillment_route_proposal (
      id TEXT PRIMARY KEY,tenant_id TEXT,case_id TEXT,proposal_version TEXT,mode TEXT,status TEXT,
      destination_token TEXT,eta_min_days INTEGER,eta_max_days INTEGER,components_json TEXT,
      state_prevented TEXT,pii_release_authorized INTEGER,created_at TEXT,
      UNIQUE(tenant_id,case_id,proposal_version))"""))
    args = dict(
        tenant_id="t1", case_id="case-1", destination_token="DEST-1",
        requested_mode="merchant_inspected", policy_modes={"merchant_inspected"},
        dispatch_days=(1, 2), transit_days=(3, 5), inspection_days=(2, 4),
        final_mile_days=(1, 2), warehouse_capacity_available=True,
    )

    first = persist_route_proposal(db, **args)
    replay = persist_route_proposal(db, **args)

    assert first["eta_days"] == {"min": 7, "max": 13}
    assert first["eta_authority"] == "calculated_range_not_promise"
    assert replay["proposal_id"] == first["proposal_id"] and replay["idempotent"] is True
    row = db.execute(text(
        "SELECT mode,status,eta_min_days,eta_max_days,pii_release_authorized "
        "FROM fulfillment_route_proposal"
    )).fetchone()
    assert tuple(row) == ("merchant_inspected", "eligible", 7, 13, 0)
