from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import text

from src.app.services.demand_allocation import (
    allocation_workbench,
    apply_supplier_schedule_to_batch,
    consolidate_shortfalls,
    create_sourcing_wave,
    materialize_governed_rfq_for_wave,
    record_demand,
)
from src.app.services.fulfillment.route_policy import (
    authorize_direct_shipping,
    evaluate_fulfillment_route,
    withdraw_direct_shipping_authorization,
)
from src.app.services.temporal_invalidation import (
    invalidate_derived_dependencies,
    invalidate_source_dependencies,
    register_derived_dependency,
    register_evidence_payload_dependencies,
)
from tests.services.test_demand_allocation import _db


def _extended_db():
    db = _db()
    return db


def _demand(db, *, key: str, sku: str, qty: int, tier: int = 50):
    return record_demand(
        db, tenant_id="t1", idempotency_key=key, case_id=key, sku=sku, quantity=qty,
        destination_id="merchant:SYD", fulfillment_location_id="SYD", stage="committed",
        priority_tier=tier, buyer_ref_hash=f"buyer-{key}",
    )


def test_two_level_wave_consolidates_compatible_sku_batches_and_is_idempotent():
    db = _extended_db()
    _demand(db, key="order-a", sku="SKU-A", qty=4)
    _demand(db, key="order-b", sku="SKU-B", qty=6)
    batches = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1", window_ends_at="2026-08-02T02:00:00Z",
    )

    first = create_sourcing_wave(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="SUP-SYD-DC",
        currency="AUD", incoterm="DAP", merchant_destination_id="merchant:SYD",
        window_ends_at="2026-08-02T02:00:00Z", batch_ids=[row["id"] for row in batches],
        standalone_freight_cents=28_000, consolidated_freight_cents=17_000,
        handling_cents=2_000,
    )
    replay = create_sourcing_wave(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="SUP-SYD-DC",
        currency="AUD", incoterm="DAP", merchant_destination_id="merchant:SYD",
        window_ends_at="2026-08-02T02:00:00Z", batch_ids=[row["id"] for row in batches],
        standalone_freight_cents=28_000, consolidated_freight_cents=17_000,
        handling_cents=2_000,
    )

    assert first["batch_count"] == 2
    assert first["line_count"] == 2
    assert first["estimated_savings_cents"] == 9_000
    assert replay["wave_id"] == first["wave_id"] and replay["idempotent"] is True
    assert db.execute(text("SELECT COUNT(*) FROM sourcing_wave")).scalar() == 1
    view = allocation_workbench(db, tenant_id="t1")
    assert view["sourcing_waves"][0]["batch_count"] == 2
    assert view["sourcing_waves"][0]["estimated_savings_cents"] == 9_000


def test_wave_rejects_cross_supplier_or_cross_destination_batch():
    db = _extended_db()
    _demand(db, key="order-a", sku="SKU-A", qty=4)
    batch = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-OTHER", window_ends_at="2026-08-02T02:00:00Z",
    )[0]

    result = create_sourcing_wave(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="SUP-SYD-DC",
        currency="AUD", incoterm="DAP", merchant_destination_id="merchant:SYD",
        window_ends_at="2026-08-02T02:00:00Z", batch_ids=[batch["id"]],
        standalone_freight_cents=10_000, consolidated_freight_cents=8_000,
        handling_cents=0,
    )

    assert result["status"] == "blocked"
    assert result["state_prevented"] == "incompatible_sourcing_batch"


def test_wave_materializes_one_supplier_bound_multiline_rfq_and_preserves_children(monkeypatch):
    db = _extended_db()
    _demand(db, key="order-a", sku="SKU-A", qty=4)
    _demand(db, key="order-b", sku="SKU-B", qty=6)
    batches = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1", window_ends_at="2026-08-02T02:00:00Z",
    )
    wave = create_sourcing_wave(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="SUP-SYD-DC",
        currency="AUD", incoterm="DAP", merchant_destination_id="merchant:SYD",
        window_ends_at="2026-08-02T02:00:00Z", batch_ids=[row["id"] for row in batches],
        standalone_freight_cents=28_000, consolidated_freight_cents=17_000,
        handling_cents=2_000,
    )
    db.execute(text(
        "INSERT INTO suppliers (id,name,reliability_score,active) VALUES "
        "('SUP-1','Supplier One',0.93,1)"
    ))
    db.execute(text(
        "INSERT INTO trusted_supplier_domains (id,domain,supplier_id,added_at,active) VALUES "
        "('D-1','supplier-one.example','SUP-1','2026-08-01T00:00:00Z',1)"
    ))
    captured = {}
    from src.app.services.fulfillment import draft as supplier_draft
    from src.app.services.fulfillment import workflow

    monkeypatch.setattr(workflow, "open_case", lambda *args, **kwargs: "CASE-WAVE-1")
    monkeypatch.setattr(
        workflow, "transition", lambda *args, **kwargs: SimpleNamespace(ok=True, reason=None),
    )

    def _draft(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(ok=True, reason=None), SimpleNamespace(content_hash="HASH-WAVE-1")

    monkeypatch.setattr(supplier_draft, "draft_and_record", _draft)
    first = materialize_governed_rfq_for_wave(
        db, tenant_id="t1", wave_id=wave["wave_id"], trace_id="TRACE-WAVE-1",
    )
    replay = materialize_governed_rfq_for_wave(
        db, tenant_id="t1", wave_id=wave["wave_id"], trace_id="TRACE-WAVE-1",
    )

    assert first["status"] == "drafted"
    assert first["child_batch_count"] == 2 and first["child_demand_count"] == 2
    assert first["lines"] == [
        {"item_ref": "SKU-A", "quantity": 4},
        {"item_ref": "SKU-B", "quantity": 6},
    ]
    assert captured["supplier_override"][:2] == ("SUP-1", "supplier-one.example")
    assert captured["lines"] == first["lines"]
    assert replay["idempotent"] is True
    assert replay["parent_rfq_ref"] == first["parent_rfq_ref"]
    assert first["supplier_response_expectation"] == {
        "calendar_state": "unknown", "sla_clock": "unknown",
        "reason": "temporal_authority_schema_unavailable", "freshness": "missing",
    }
    assert db.execute(text(
        "SELECT COUNT(DISTINCT fulfillment_case_id) FROM sourcing_batch"
    )).scalar() == 1


def test_direct_shipping_requires_active_minimal_scoped_authorization_and_withdrawal_blocks():
    db = _extended_db()
    retention = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    grant = authorize_direct_shipping(
        db, tenant_id="t1", case_id="CASE-1", supplier_id="SUP-1",
        destination_token="DEST-1", jurisdiction="AU-NSW", purpose="deliver_order",
        permitted_fields={"recipient_name", "street_address", "postal_code"},
        retention_until=retention, authorized_by="buyer-subject", audit_evidence_id="AUD-1",
    )
    allowed = evaluate_fulfillment_route(
        requested_mode="supplier_direct", policy_modes={"supplier_direct"},
        dispatch_days=(1, 2), transit_days=(2, 3), inspection_days=(0, 0),
        final_mile_days=(1, 1), destination_token="DEST-1",
        buyer_destination={"recipient_name": "Ada", "street_address": "1 Main St",
                           "postal_code": "2000", "email": "not-needed@example.test"},
        privacy_authorization=grant, supplier_id="SUP-1", supplier_jurisdiction="AU-NSW",
        supplier_capability={"status": "verified", "direct_ship": True,
                             "returns_owner": "merchant"},
    )
    withdrawn = withdraw_direct_shipping_authorization(
        db, tenant_id="t1", authorization_id=grant["authorization_id"], actor_id="buyer-subject",
    )
    blocked = evaluate_fulfillment_route(
        requested_mode="supplier_direct", policy_modes={"supplier_direct"},
        dispatch_days=(1, 2), transit_days=(2, 3), inspection_days=(0, 0),
        final_mile_days=(1, 1), destination_token="DEST-1", buyer_destination={},
        privacy_authorization=withdrawn, supplier_id="SUP-1", supplier_jurisdiction="AU-NSW",
        supplier_capability={"status": "verified", "direct_ship": True},
    )

    assert allowed["status"] == "eligible"
    assert allowed["supplier_destination"] == {
        "recipient_name": "Ada", "street_address": "1 Main St", "postal_code": "2000"
    }
    assert allowed["privacy"]["fields_withheld"] == ["email"]
    assert blocked["status"] == "blocked"
    assert blocked["state_prevented"] == "buyer_pii_release"


def test_cross_dock_and_split_routes_expose_capacity_cost_return_and_eta_components():
    cross_dock = evaluate_fulfillment_route(
        requested_mode="cross_dock", policy_modes={"cross_dock"}, dispatch_days=(1, 2),
        transit_days=(2, 3), inspection_days=(0, 0), cross_dock_days=(1, 2),
        final_mile_days=(1, 1), buyer_destination={}, destination_token="DEST-1",
        warehouse_capacity_available=True, required_capacity_units=80, available_capacity_units=100,
        supplier_capability={"status": "verified", "cross_dock": True,
                             "returns_owner": "merchant"},
        cost_components_cents={"inbound_freight": 12000, "handling": 2500,
                               "final_mile": 9000}, cost_currency="AUD",
    )
    split = evaluate_fulfillment_route(
        requested_mode="split", policy_modes={"split"}, dispatch_days=(0, 1),
        transit_days=(1, 2), inspection_days=(0, 0), final_mile_days=(1, 1),
        buyer_destination={}, destination_token="DEST-1",
        supplier_capability={"status": "verified", "split": True,
                             "returns_owner": "merchant"},
        split_shipments=[{"source": "internal", "quantity": 53, "eta_days": [1, 3]},
                         {"source": "supplier", "quantity": 27, "eta_days": [6, 10]}],
        cost_components_cents={"shipment_1": 9000, "shipment_2": 14000}, cost_currency="AUD",
    )

    assert cross_dock["eta_days"] == {"min": 5, "max": 8}
    assert cross_dock["cost_to_serve"] == {"currency": "AUD", "total_cents": 23500,
                                            "components": {"final_mile": 9000,
                                                           "handling": 2500,
                                                           "inbound_freight": 12000}}
    assert cross_dock["return_owner"] == "merchant"
    assert split["shipment_count"] == 2
    assert split["eta_days"] == {"min": 1, "max": 10}


def test_supplier_batch_partial_confirmation_updates_every_child_without_overclaiming():
    db = _extended_db()
    first = _demand(db, key="order-priority", sku="SKU-A", qty=4, tier=10)
    second = _demand(db, key="order-standard", sku="SKU-A", qty=6, tier=50)
    batch = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1", window_ends_at="2026-08-02T02:00:00Z",
    )[0]

    result = apply_supplier_schedule_to_batch(
        db, tenant_id="t1", batch_id=batch["id"], supplier_id="SUP-1",
        evidence_id="SUP-REPLY-1", schedule_lines=[
            {"status": "partial", "quantity": 7, "eta": "2026-08-09"},
            {"status": "rejected", "quantity": 3},
        ], observed_at="2026-08-02T01:00:00Z",
    )

    by_demand = {row["demand_id"]: row for row in result["demands"]}
    assert by_demand[first["id"]]["supplier_confirmed_qty"] == 4
    assert by_demand[second["id"]]["supplier_confirmed_qty"] == 3
    assert by_demand[second["id"]]["shortfall_qty"] == 3
    assert result["confirmed_quantity"] == 7
    assert result["unresolved_quantity"] == 3
    assert result["alternatives_required"] is True


def test_temporal_invalidation_retracts_every_registered_derived_surface_idempotently():
    db = _extended_db()
    for derived_type, derived_id in (
        ("hippograph_edge", "EDGE-1"), ("market_evidence_bundle", "BUNDLE-1"),
        ("procurement_proposal", "PROP-1"), ("narration_fingerprint", "NARR-1"),
    ):
        register_derived_dependency(
            db, tenant_id="t1", source_type="supplier_fact", source_id="FACT-1",
            source_version="v1", derived_type=derived_type, derived_id=derived_id,
        )

    first = invalidate_source_dependencies(
        db, tenant_id="t1", source_type="supplier_fact", source_id="FACT-1",
        source_version="v1", reason="superseded_by:v2",
    )
    replay = invalidate_source_dependencies(
        db, tenant_id="t1", source_type="supplier_fact", source_id="FACT-1",
        source_version="v1", reason="superseded_by:v2",
    )

    assert first["invalidated_count"] == 4
    assert {row["derived_type"] for row in first["invalidated"]} == {
        "hippograph_edge", "market_evidence_bundle", "procurement_proposal",
        "narration_fingerprint",
    }
    assert replay["invalidated_count"] == 0


def test_rebuilt_derived_surface_invalidates_prior_source_bindings():
    db = _extended_db()
    register_derived_dependency(
        db, tenant_id="t1", source_type="supplier_schedule", source_id="reply-1",
        source_version="v1", derived_type="buyer_supply_promise", derived_id="demand-1",
    )
    result = invalidate_derived_dependencies(
        db, tenant_id="t1", derived_type="buyer_supply_promise", derived_id="demand-1",
        reason="superseded_by:reply-2",
    )
    assert result["invalidated_count"] == 1
    assert db.execute(text(
        "SELECT status FROM temporal_dependency WHERE derived_id='demand-1'"
    )).scalar() == "invalidated"


def test_evidence_registration_refuses_to_invent_versions():
    db = _extended_db()
    result = register_evidence_payload_dependencies(
        db, tenant_id="t1", derived_type="market_evidence_bundle", derived_id="decision-1",
        default_source_type="market_evidence", evidence_items=[
            {"evidence_id": "E-1", "observed_at": "2026-08-02T00:00:00Z"},
            {"evidence_id": "E-2"},
            {"label": "unattributed claim"},
        ],
    )
    assert result["registered_count"] == 1
    assert result["skipped_count"] == 2
    assert db.execute(text("SELECT source_id FROM temporal_dependency")).scalar() == "E-1"
