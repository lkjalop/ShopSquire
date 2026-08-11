import json
import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.demand_allocation import (
    allocate_committed,
    allocation_shadow_parity,
    allocation_shadow_parity_from_register,
    allocation_workbench,
    apply_supplier_schedule,
    commit_demand,
    consolidate_shortfalls,
    create_sourcing_wave,
    project_committed_order_demand,
    record_demand,
    sync_provisional_cart_demand,
    sync_authoritative_location_atp,
    transition_demand,
    upsert_supply_snapshot,
)
from src.app.services.allocation_parity_exceptions import (
    canonical_exception_bytes,
    store_verified_exception,
)
from src.app.services.sourcing_backpressure import (
    SourcingBackpressurePolicy,
    SourcingQueueState,
)
from src.app.services.supplier_sourcing_authority import (
    load_sourcing_admission_context,
    persist_sourcing_policy,
    record_sourcing_queue_observation,
)


def _db():
    db = sessionmaker(bind=create_engine("sqlite://"))()
    db.execute(text("""CREATE TABLE demand_commitment (
      id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,case_id TEXT,
      buyer_ref_hash TEXT,sku TEXT NOT NULL,uom TEXT NOT NULL,destination_id TEXT NOT NULL,
      stage TEXT NOT NULL,quantity INTEGER NOT NULL,priority_tier INTEGER NOT NULL,required_by TEXT,
      created_at TEXT NOT NULL,updated_at TEXT NOT NULL,fulfillment_location_id TEXT,
      UNIQUE(tenant_id,idempotency_key))"""))
    db.execute(text("""CREATE TABLE supply_allocation_pool (
      tenant_id TEXT,sku TEXT,uom TEXT,location_id TEXT,atp_quantity INTEGER,snapshot_version TEXT,
      observed_at TEXT,expires_at TEXT,source_id TEXT,source_authority TEXT,completeness TEXT,
      source_observation_id TEXT,PRIMARY KEY(tenant_id,sku,uom,location_id))"""))
    db.execute(text("""CREATE TABLE demand_allocation (
      id TEXT PRIMARY KEY,tenant_id TEXT,demand_id TEXT,sku TEXT,uom TEXT,location_id TEXT,
      quantity INTEGER,status TEXT,created_at TEXT,released_at TEXT,
      UNIQUE(tenant_id,demand_id,location_id))"""))
    db.execute(text("""CREATE TABLE sourcing_batch (
      id TEXT PRIMARY KEY,tenant_id TEXT,idempotency_key TEXT,consolidation_key TEXT,sku TEXT,uom TEXT,
      destination_id TEXT,supplier_id TEXT,status TEXT,quantity INTEGER,speculative_quantity INTEGER,
      window_ends_at TEXT,created_at TEXT,fulfillment_case_id TEXT,draft_content_hash TEXT,updated_at TEXT,
      UNIQUE(tenant_id,idempotency_key))"""))
    db.execute(text("""CREATE TABLE sourcing_batch_demand (
      batch_id TEXT,demand_id TEXT,quantity INTEGER,PRIMARY KEY(batch_id,demand_id))"""))
    db.execute(text("""CREATE TABLE sourcing_wave (
      id TEXT PRIMARY KEY,tenant_id TEXT,idempotency_key TEXT,supplier_id TEXT,
      supplier_facility_id TEXT,currency TEXT,incoterm TEXT,merchant_destination_id TEXT,
      status TEXT,window_ends_at TEXT,standalone_freight_cents INTEGER,
      consolidated_freight_cents INTEGER,handling_cents INTEGER,estimated_savings_cents INTEGER,
      created_at TEXT,updated_at TEXT,fulfillment_case_id TEXT,draft_content_hash TEXT,
      parent_rfq_ref TEXT,UNIQUE(tenant_id,idempotency_key),UNIQUE(tenant_id,parent_rfq_ref))"""))
    db.execute(text("""CREATE TABLE sourcing_wave_batch (
      wave_id TEXT,batch_id TEXT,PRIMARY KEY(wave_id,batch_id),UNIQUE(batch_id))"""))
    db.execute(text("""CREATE TABLE allocation_shadow_parity_run (
      id TEXT PRIMARY KEY,tenant_id TEXT,case_id TEXT,status TEXT,new_allocated_qty INTEGER,
      legacy_reserved_qty INTEGER,details_json TEXT,created_at TEXT)"""))
    db.execute(text("""CREATE TABLE allocation_parity_exception (
      id TEXT PRIMARY KEY,tenant_id TEXT,case_id TEXT,sku TEXT,difference_code TEXT,
      rationale TEXT,evidence_ref TEXT,signer_id TEXT,key_id TEXT,payload_json TEXT,
      signature_b64 TEXT,valid_from TEXT,expires_at TEXT,revoked_at TEXT,created_at TEXT,
      UNIQUE(tenant_id,case_id,sku,difference_code,signature_b64))"""))
    db.execute(text("""CREATE TABLE supplier_schedule_allocation (
      id TEXT PRIMARY KEY,tenant_id TEXT,demand_id TEXT,supplier_id TEXT,evidence_id TEXT,status TEXT,
      quantity INTEGER,eta TEXT,observed_at TEXT,expires_at TEXT,created_at TEXT,
      UNIQUE(tenant_id,demand_id,evidence_id))"""))
    db.execute(text("""CREATE TABLE buyer_supply_promise (
      tenant_id TEXT,demand_id TEXT,promise_version TEXT,promise_state TEXT,covered_quantity INTEGER,
      shortfall_quantity INTEGER,buyer_message TEXT,alternatives_required INTEGER,updated_at TEXT,
      PRIMARY KEY(tenant_id,demand_id))"""))
    db.execute(text("""CREATE TABLE fulfillment_route_proposal (
      id TEXT PRIMARY KEY,tenant_id TEXT,case_id TEXT,proposal_version TEXT,mode TEXT,status TEXT,
      destination_token TEXT,eta_min_days INTEGER,eta_max_days INTEGER,components_json TEXT,
      state_prevented TEXT,pii_release_authorized INTEGER,created_at TEXT,
      UNIQUE(tenant_id,case_id,proposal_version))"""))
    db.execute(text("""CREATE TABLE direct_ship_authorization (
      id TEXT PRIMARY KEY,tenant_id TEXT,case_id TEXT,supplier_id TEXT,destination_token TEXT,
      jurisdiction TEXT,purpose TEXT,permitted_fields_json TEXT,retention_until TEXT,status TEXT,
      authorized_by TEXT,authorized_at TEXT,withdrawn_at TEXT,audit_evidence_id TEXT,
      idempotency_key TEXT,UNIQUE(tenant_id,idempotency_key))"""))
    db.execute(text("""CREATE TABLE supplier_sourcing_policy (
      id TEXT PRIMARY KEY,tenant_id TEXT,supplier_id TEXT,supplier_facility_id TEXT,
      policy_version TEXT,max_open_requests INTEGER,max_open_units INTEGER,
      max_request_units INTEGER,max_dispatches_per_hour INTEGER,
      acknowledgement_sla_seconds INTEGER,effective_from TEXT,status TEXT,created_at TEXT,
      UNIQUE(tenant_id,supplier_id,supplier_facility_id,policy_version))"""))
    db.execute(text("""CREATE TABLE supplier_sourcing_queue_observation (
      id TEXT PRIMARY KEY,tenant_id TEXT,supplier_id TEXT,supplier_facility_id TEXT,
      source_id TEXT,source_version TEXT,observed_at TEXT,expires_at TEXT,
      open_requests INTEGER,open_units INTEGER,dispatches_last_hour INTEGER,
      oldest_unacknowledged_at TEXT,created_at TEXT,
      UNIQUE(tenant_id,supplier_id,supplier_facility_id,source_id,source_version))"""))
    db.execute(text("""CREATE TABLE temporal_dependency (
      id TEXT PRIMARY KEY,tenant_id TEXT,source_type TEXT,source_id TEXT,source_version TEXT,
      derived_type TEXT,derived_id TEXT,status TEXT,created_at TEXT,invalidated_at TEXT,
      invalidation_reason TEXT,UNIQUE(tenant_id,source_type,source_id,source_version,derived_type,derived_id))"""))
    db.execute(text("""CREATE TABLE suppliers (
      id TEXT PRIMARY KEY,name TEXT,reliability_score REAL,active INTEGER)"""))
    db.execute(text("""CREATE TABLE trusted_supplier_domains (
      id TEXT PRIMARY KEY,domain TEXT,supplier_id TEXT,added_at TEXT,active INTEGER)"""))
    return db


def _snapshot(db, *, qty: int, version: str = "v1", observed: str = "2026-08-02T00:00:00Z",
              expires: str | None = None):
    return upsert_supply_snapshot(
        db, tenant_id="t1", sku="SKU-1", uom="each", location_id="SYD",
        atp_quantity=qty, snapshot_version=version, observed_at=observed, expires_at=expires,
        source_id="wms", source_authority="authoritative", completeness="source_supplied",
        source_observation_id=f"obs-{version}",
    )


def _demand(db, key, *, stage="provisional", qty=3, tier=100, tenant="t1"):
    return record_demand(db, tenant_id=tenant, idempotency_key=key, sku="SKU-1",
                         quantity=qty, destination_id="SYD", stage=stage,
                         priority_tier=tier, buyer_ref_hash=f"hash-{key}",
                         fulfillment_location_id="SYD")


def test_provisional_query_visibility_cannot_reserve_inventory():
    db = _db()
    _demand(db, "cart-1", stage="provisional", qty=8)
    _snapshot(db, qty=5)

    result = allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")

    assert result["allocated"] == []
    assert db.execute(text("SELECT COUNT(*) FROM demand_allocation")).scalar() == 0


def test_eight_commitments_never_overallocate_and_priority_is_traceable():
    db = _db()
    demands = [_demand(db, f"order-{i}", stage="committed", qty=2, tier=10 if i == 7 else 100)
               for i in range(8)]
    _snapshot(db, qty=9, version="v7")

    result = allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")

    assert result["conservation_ok"] is True
    assert sum(row["quantity"] for row in result["allocated"]) == 9
    assert result["allocated"][0]["demand_id"] == demands[7]["id"]
    assert result["allocated"][0]["priority_tier"] == 10


def test_later_amendment_does_not_steal_an_existing_allocation():
    db = _db()
    first = _demand(db, "first", stage="committed", qty=5)
    _snapshot(db, qty=5)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")
    _demand(db, "later-high-priority", stage="committed", qty=5, tier=1)

    second = allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")

    assert second["allocated"] == []
    owner = db.execute(text(
        "SELECT demand_id,quantity FROM demand_allocation WHERE status='allocated'"
    )).fetchone()
    assert tuple(owner) == (first["id"], 5)


def test_newer_supply_snapshot_extends_partial_allocation_without_duplicate_row():
    db = _db()
    demand = _demand(db, "partial", stage="committed", qty=8)
    _snapshot(db, qty=3)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")
    _snapshot(db, qty=8, version="v2", observed="2026-08-02T00:05:00Z")

    result = allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")

    assert result["conservation_ok"] is True
    row = db.execute(text(
        "SELECT demand_id,quantity,COUNT(*) FROM demand_allocation GROUP BY demand_id,quantity"
    )).fetchone()
    assert tuple(row) == (demand["id"], 8, 1)


def test_scope_and_replay_are_tenant_safe_and_idempotent():
    db = _db()
    original = _demand(db, "same-key", stage="provisional")
    replay = _demand(db, "same-key", stage="committed", qty=99)
    other = _demand(db, "same-key", stage="committed", tenant="t2")

    assert replay["id"] == original["id"] and replay["idempotent"] is True
    assert replay["quantity"] == 3 and replay["stage"] == "provisional"
    assert other["id"] != original["id"]
    promoted = commit_demand(db, tenant_id="t1", demand_id=original["id"])
    assert promoted["stage"] == "committed" and promoted["changed"] is True


def test_compatible_shortfalls_create_one_idempotent_batch_with_child_demands():
    db = _db()
    one = _demand(db, "one", stage="committed", qty=5)
    two = _demand(db, "two", stage="committed", qty=7)
    _snapshot(db, qty=4)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")

    first = consolidate_shortfalls(db, tenant_id="t1", supplier_id="SUP-1",
                                   window_ends_at="2026-08-02T01:00:00Z")
    replay = consolidate_shortfalls(db, tenant_id="t1", supplier_id="SUP-1",
                                    window_ends_at="2026-08-02T01:00:00Z")

    assert len(first) == 1 and first[0]["quantity"] == 8
    assert first[0]["speculative_quantity"] == 0
    children = db.execute(text(
        "SELECT demand_id,quantity FROM sourcing_batch_demand ORDER BY demand_id"
    )).fetchall()
    assert {row[0] for row in children} == {one["id"], two["id"]}
    assert replay[0]["id"] == first[0]["id"] and replay[0]["idempotent"] is True


def test_cart_projection_is_provisional_updates_in_place_and_cancels_removed_lines():
    db = _db()
    first = sync_provisional_cart_demand(
        db, tenant_id="t1", cart_id="cart-1", buyer_ref_hash="buyer-hash",
        items=[{"sku": "SKU-1", "quantity": 3}], destination_id="destination-unset",
    )
    second = sync_provisional_cart_demand(
        db, tenant_id="t1", cart_id="cart-1", buyer_ref_hash="buyer-hash",
        items=[{"sku": "SKU-1", "quantity": 8}], destination_id="destination-unset",
    )
    removed = sync_provisional_cart_demand(
        db, tenant_id="t1", cart_id="cart-1", buyer_ref_hash="buyer-hash", items=[],
    )

    assert first["allocates_supply"] is False
    assert second["changed"][0]["quantity"] == 8
    assert removed["changed"][0]["quantity"] == 0
    row = db.execute(text(
        "SELECT stage,quantity FROM demand_commitment WHERE case_id='cart-1'"
    )).fetchone()
    assert tuple(row) == ("cancelled", 8)


def test_cancel_releases_allocation_and_fulfilled_consumes_it():
    db = _db()
    cancelled = _demand(db, "cancel", stage="committed", qty=2)
    fulfilled = _demand(db, "fulfill", stage="committed", qty=2)
    _snapshot(db, qty=4)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")

    transition_demand(db, tenant_id="t1", demand_id=cancelled["id"], target_stage="cancelled")
    transition_demand(db, tenant_id="t1", demand_id=fulfilled["id"], target_stage="fulfilled")

    states = dict(db.execute(text(
        "SELECT demand_id,status FROM demand_allocation ORDER BY demand_id"
    )).fetchall())
    assert states[cancelled["id"]] == "released"
    assert states[fulfilled["id"]] == "consumed"


def test_expired_atp_is_unknown_and_cannot_allocate():
    db = _db()
    _demand(db, "stale", stage="committed", qty=2)
    _snapshot(db, qty=10, version="stale-v1", observed="2025-01-01T00:00:00Z",
              expires="2025-01-02T00:00:00Z")

    result = allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")

    assert result["status"] == "stale_supply"
    assert db.execute(text("SELECT COUNT(*) FROM demand_allocation")).scalar() == 0


def test_new_compatible_child_appends_to_open_sourcing_window():
    db = _db()
    _demand(db, "first-window", stage="committed", qty=3)
    first = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1", window_ends_at="2026-08-02T01:00:00Z"
    )[0]
    second_demand = _demand(db, "second-window", stage="committed", qty=4)
    second = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1", window_ends_at="2026-08-02T01:00:00Z"
    )[0]

    assert second["id"] == first["id"]
    assert second["quantity"] == 7
    assert second["children_appended"] == [(second_demand["id"], 4)]
    assert db.execute(text("SELECT COUNT(*) FROM sourcing_batch")).scalar() == 1


def test_sourcing_backpressure_is_typed_and_non_executable():
    db = _db()
    _demand(db, "too-large", stage="committed", qty=12)

    result = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1", window_ends_at="2026-08-02T01:00:00Z",
        max_batch_quantity=10,
    )[0]

    assert result == {"status": "blocked", "reason": "supplier_capacity_limit",
                      "sku": "SKU-1", "quantity": 12}
    assert db.execute(text("SELECT COUNT(*) FROM sourcing_batch")).scalar() == 0


def test_supplier_queue_policy_prevents_new_contact_and_routes_urgent_alternative():
    db = _db()
    _demand(db, "urgent-overload", stage="committed", qty=12)
    policy = SourcingBackpressurePolicy(
        max_open_requests=2, max_open_units=100, max_request_units=50,
        max_dispatches_per_hour=2, acknowledgement_sla=timedelta(hours=2),
    )
    queue = SourcingQueueState(
        open_requests=2, open_units=80, dispatches_last_hour=2,
        oldest_unacknowledged_at=datetime.now(timezone.utc) - timedelta(hours=3),
    )

    result = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1",
        window_ends_at="2026-08-02T01:00:00Z", urgency_bypass=True,
        backpressure_policy=policy, supplier_queue_state=queue,
    )[0]

    assert result["status"] == "blocked"
    assert result["reason"] == "supplier_backpressure"
    assert result["admission_action"] == "seek_alternative"
    assert result["external_contact_permitted"] is False
    assert "query_approved_alternative_supplier" in result["next_permitted_actions"]


def test_persisted_supplier_authority_drives_consolidation_backpressure():
    db = _db()
    _demand(db, "supplier-pressure", stage="committed", qty=6, tier=20)
    persist_sourcing_policy(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        policy_version="policy-v1", max_open_requests=2, max_open_units=10,
        max_request_units=8, max_dispatches_per_hour=4,
        acknowledgement_sla_seconds=900, effective_from="2026-08-03T00:00:00Z",
    )
    record_sourcing_queue_observation(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        source_id="portal-adapter", source_version="queue-v1",
        observed_at="2026-08-03T00:10:00Z", expires_at="2026-08-03T01:10:00Z",
        open_requests=2, open_units=7, dispatches_last_hour=1,
        oldest_unacknowledged_at="2026-08-03T00:05:00Z",
    )
    context = load_sourcing_admission_context(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        now=datetime(2026, 8, 3, 0, 20, tzinfo=timezone.utc),
    )

    result = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1",
        window_ends_at="2026-08-03T00:30:00Z", urgency_bypass=True,
        backpressure_policy=context["policy"], supplier_queue_state=context["state"],
    )[0]

    assert context["status"] == "ready"
    assert result["status"] == "blocked"
    assert result["admission_action"] == "seek_alternative"
    assert result["external_contact_permitted"] is False
    assert "supplier_open_request_limit" in result["reason_codes"]


def test_stale_supplier_queue_cannot_be_used_for_admission():
    db = _db()
    persist_sourcing_policy(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        policy_version="policy-v1", max_open_requests=2, max_open_units=10,
        max_request_units=8, max_dispatches_per_hour=4,
        acknowledgement_sla_seconds=900, effective_from="2026-08-03T00:00:00Z",
    )
    record_sourcing_queue_observation(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        source_id="email-adapter", source_version="queue-v1",
        observed_at="2026-08-03T00:10:00Z", expires_at="2026-08-03T00:15:00Z",
        open_requests=0, open_units=0, dispatches_last_hour=0,
    )

    context = load_sourcing_admission_context(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        now=datetime(2026, 8, 3, 0, 20, tzinfo=timezone.utc),
    )

    assert context["status"] == "degraded"
    assert context["policy"] is None and context["state"] is None
    assert "supplier_queue_stale" in context["reason_codes"]


def test_consolidation_route_fails_closed_on_stale_persisted_supplier_authority(monkeypatch):
    from src.app.routers import allocation as allocation_router

    db = _db()
    _demand(db, "route-pressure", stage="committed", qty=6, tier=20)
    persist_sourcing_policy(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        policy_version="policy-v1", max_open_requests=2, max_open_units=10,
        max_request_units=8, max_dispatches_per_hour=4,
        acknowledgement_sla_seconds=900, effective_from="2026-08-01T00:00:00Z",
    )
    record_sourcing_queue_observation(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        source_id="portal-adapter", source_version="queue-stale",
        observed_at="2026-08-01T00:10:00Z", expires_at="2026-08-01T00:15:00Z",
        open_requests=0, open_units=0, dispatches_last_hour=0,
    )
    monkeypatch.setattr(allocation_router, "db_session", lambda: db)
    monkeypatch.setattr(allocation_router, "_tenant", lambda: "t1")

    result = allocation_router.consolidate(
        allocation_router.ConsolidateBody(
            supplier_id="SUP-1", supplier_facility_id="FAC-1",
            window_ends_at="2026-08-04T00:00:00Z", urgency_bypass=False,
        ),
        role="owner",
    )

    assert result["batches"][0]["status"] == "blocked"
    assert result["batches"][0]["state_prevented"] == "new_supplier_request"
    assert result["external_action"] == "none"
    assert db.execute(text("SELECT COUNT(*) FROM sourcing_batch")).scalar() == 0


def test_buyer_confirmation_promotes_matching_cart_without_allocating():
    db = _db()
    sync_provisional_cart_demand(
        db, tenant_id="t1", cart_id="order-1", buyer_ref_hash="buyer-hash",
        items=[{"sku": "SKU-1", "quantity": 3}],
    )

    result = project_committed_order_demand(
        db, tenant_id="t1", order_id="order-1", buyer_ref_hash="buyer-hash",
        lines=[{"item_ref": "SKU-1", "requested_qty": 8,
                "availability": {"preferred_location": "WH-SYD-01"}}],
        destination_id="destination:buyer-sydney",
        required_by="2026-09-18",
    )

    assert result["authority"] == "buyer_committed"
    assert result["allocates_supply"] is False
    row = db.execute(text(
        "SELECT stage,quantity,destination_id,required_by,fulfillment_location_id "
        "FROM demand_commitment"
    )).fetchone()
    assert tuple(row) == (
        "committed", 8, "destination:buyer-sydney", "2026-09-18", "WH-SYD-01"
    )
    assert db.execute(text("SELECT COUNT(*) FROM demand_allocation")).scalar() == 0


def test_confirmation_without_cart_is_idempotent_committed_demand():
    db = _db()
    args = dict(
        tenant_id="t1", order_id="order-2", buyer_ref_hash="buyer-hash",
        lines=[{"sku": "SKU-1", "quantity": 4}], destination_id="SYD",
    )
    first = project_committed_order_demand(db, **args)
    replay = project_committed_order_demand(db, **args)

    assert first["demands"][0]["id"] == replay["demands"][0]["id"]
    assert replay["demands"][0]["idempotent"] is True
    assert db.execute(text("SELECT COUNT(*) FROM demand_commitment")).scalar() == 1


def test_governed_amendment_cancels_prior_shadow_commitment_and_versions_replacement():
    db = _db()
    base = dict(
        tenant_id="t1", order_id="order-3", buyer_ref_hash="buyer-hash",
        destination_id="SYD",
    )
    first = project_committed_order_demand(
        db, **base, lines=[{"sku": "SKU-1", "quantity": 4}],
    )
    amended = project_committed_order_demand(
        db, **base, lines=[{"sku": "SKU-1", "quantity": 7}], amendment_version="trace-2",
    )

    assert first["demands"][0]["id"] != amended["demands"][0]["id"]
    rows = db.execute(text(
        "SELECT stage,quantity FROM demand_commitment ORDER BY created_at,id"
    )).fetchall()
    assert sorted(tuple(row) for row in rows) == [("cancelled", 4), ("committed", 7)]


def test_older_atp_snapshot_cannot_overwrite_newer_authoritative_truth():
    db = _db()
    _snapshot(db, qty=8, version="new", observed="2026-08-02T01:00:00Z")

    result = _snapshot(db, qty=99, version="old", observed="2026-08-02T00:00:00Z")

    assert result["status"] == "superseded"
    row = db.execute(text(
        "SELECT atp_quantity,snapshot_version,source_authority FROM supply_allocation_pool"
    )).fetchone()
    assert tuple(row) == (8, "new", "authoritative")


def test_new_atp_version_invalidates_allocations_derived_from_prior_snapshot():
    db = _db()
    _demand(db, "temporal-atp", stage="committed", qty=3)
    _snapshot(db, qty=3, version="v1", observed="2026-08-02T00:00:00Z")
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")

    _snapshot(db, qty=2, version="v2", observed="2026-08-02T00:05:00Z")

    row = db.execute(text(
        "SELECT status,invalidation_reason FROM temporal_dependency "
        "WHERE derived_type='allocation_projection'"
    )).fetchone()
    assert tuple(row) == ("invalidated", "superseded_by:v2")


def test_canonical_location_atp_projects_source_version_freshness_and_authority():
    db = _db()
    db.execute(text("""CREATE TABLE authoritative_business_observation (
      id TEXT PRIMARY KEY,tenant_id TEXT,source TEXT,entity_type TEXT,event_time TEXT,payload_json TEXT,
      feed_run_id TEXT,quality_status TEXT,event_kind TEXT,reverses_observation_id TEXT)"""))
    payload = {
        "kind": "location_atp", "variant_id": "SKU-1", "location_id": "SYD",
        "source_atp": {"value": "12", "uom": "each"}, "source_basis": ["wms_atp"],
        "source_calculated_at": "2026-08-02T00:00:00Z", "ttl_seconds": 3600,
    }
    db.execute(text(
        "INSERT INTO authoritative_business_observation VALUES "
        "('obs-1','t1','wms','location_atp','2026-08-02T00:00:00Z',:payload,"
        "'feed-v7','accepted','observation',NULL)"
    ), {"payload": json.dumps(payload)})

    result = sync_authoritative_location_atp(
        db, tenant_id="t1", source="wms",
        now=datetime(2026, 8, 2, 0, 10, tzinfo=timezone.utc),
    )

    assert result["status"] == "ready"
    row = db.execute(text(
        "SELECT atp_quantity,snapshot_version,source_authority,completeness,source_observation_id "
        "FROM supply_allocation_pool"
    )).fetchone()
    assert tuple(row) == (12, "feed-v7", "authoritative", "source_supplied", "obs-1")


def test_shadow_parity_reports_legacy_scope_limitations_and_quantity_match():
    db = _db()
    demand = record_demand(
        db, tenant_id="t1", idempotency_key="order-9", case_id="order-9", sku="SKU-1",
        quantity=3, destination_id="destination:buyer", stage="committed", priority_tier=50,
        fulfillment_location_id="SYD",
    )
    _snapshot(db, qty=3)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")
    db.execute(text("""CREATE TABLE inventory_reservations (
      id TEXT PRIMARY KEY,order_id TEXT,sku TEXT,qty INTEGER,status TEXT)"""))
    db.execute(text(
        "INSERT INTO inventory_reservations VALUES ('r1','order-9','SKU-1',3,'reserved')"
    ))

    report = allocation_shadow_parity(db, tenant_id="t1", case_id="order-9")

    assert report["status"] == "match"
    assert report["new_allocated_qty"] == report["legacy_reserved_qty"] == 3
    assert report["comparisons"][0]["case_id"] == "order-9"
    assert "legacy_reservations_not_tenant_scoped" in report["limitations"]
    assert demand["id"]


def test_shadow_parity_classifies_and_requires_explicit_difference_acceptance():
    db = _db()
    record_demand(
        db, tenant_id="t1", idempotency_key="order-10", case_id="order-10",
        sku="SKU-1", quantity=5, destination_id="destination:buyer",
        stage="committed", priority_tier=50, fulfillment_location_id="SYD",
    )
    _snapshot(db, qty=5)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")
    db.execute(text("""CREATE TABLE inventory_reservations (
      id TEXT PRIMARY KEY,order_id TEXT,sku TEXT,qty INTEGER,status TEXT)"""))
    db.execute(text(
        "INSERT INTO inventory_reservations VALUES "
        "('r2','order-10','SKU-1',3,'reserved')"
    ))

    unexplained = allocation_shadow_parity(
        db, tenant_id="t1", case_id="order-10", persist=False,
    )
    explained = allocation_shadow_parity(
        db, tenant_id="t1", case_id="order-10", persist=False,
        accepted_difference_codes={"shadow_quantity_higher"},
    )

    assert unexplained["status"] == "diverged"
    assert unexplained["comparisons"][0]["difference_code"] == "shadow_quantity_higher"
    assert unexplained["unaccepted_difference_count"] == 1
    assert unexplained["quantity_parity_ready"] is False
    assert explained["status"] == "explained_difference"
    assert explained["comparisons"][0]["difference_accepted"] is True
    assert explained["quantity_parity_ready"] is True
    # Legacy reservations have no tenant/location identity, so an explained
    # quantity difference is still insufficient to transfer execution authority.
    assert explained["scope_parity_ready"] is False
    assert explained["replacement_ready"] is False
    assert explained["execution_authority"] == "legacy_inventory_reservations"


def test_shadow_parity_rejects_unknown_exception_codes():
    db = _db()
    with pytest.raises(ValueError, match="unsupported_parity_difference_code"):
        allocation_shadow_parity(
            db, tenant_id="t1", persist=False,
            accepted_difference_codes={"laptop_demo_exception"},
        )


def test_signed_parity_exception_is_exact_case_scoped_and_never_transfers_authority():
    db = _db()
    record_demand(
        db, tenant_id="t1", idempotency_key="order-signed", case_id="order-signed",
        sku="SKU-1", quantity=5, destination_id="destination:buyer", stage="committed",
        priority_tier=50, fulfillment_location_id="SYD",
    )
    _snapshot(db, qty=5)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")
    db.execute(text("""CREATE TABLE inventory_reservations (
      id TEXT PRIMARY KEY,order_id TEXT,sku TEXT,qty INTEGER,status TEXT)"""))
    db.execute(text(
        "INSERT INTO inventory_reservations VALUES "
        "('signed-r1','order-signed','SKU-1',3,'reserved')"
    ))
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    payload = {
        "tenant_id": "t1", "case_id": "order-signed", "sku": "SKU-1",
        "difference_code": "shadow_quantity_higher",
        "rationale": "Legacy reservation records exclude the governed transfer quantity.",
        "evidence_ref": "parity-run:2026-08-03:001", "signer_id": "operator-7",
        "key_id": "ops-ed25519-v1", "valid_from": "2026-08-03T00:00:00Z",
        "expires_at": "2026-08-10T00:00:00Z",
    }
    signature = base64.b64encode(private_key.sign(canonical_exception_bytes(payload))).decode()
    stored = store_verified_exception(
        db, payload=payload, signature_b64=signature, public_key_bytes=public_key,
    )

    report = allocation_shadow_parity_from_register(
        db, tenant_id="t1", case_id="order-signed",
        key_resolver=lambda tenant, key_id: public_key
        if (tenant, key_id) == ("t1", "ops-ed25519-v1") else None,
        as_of=datetime(2026, 8, 4, tzinfo=timezone.utc), persist=False,
    )

    assert report["status"] == "explained_difference"
    assert report["comparisons"][0]["parity_exception_id"] == stored["id"]
    assert report["parity_exception_verification"]["status"] == "verified"
    assert report["replacement_ready"] is False
    assert report["execution_authority"] == "legacy_inventory_reservations"


def test_expired_parity_exception_fails_closed():
    db = _db()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    payload = {
        "tenant_id": "t1", "case_id": "order-expired", "sku": None,
        "difference_code": "legacy_quantity_higher",
        "rationale": "A bounded observation delay explains this measured difference.",
        "evidence_ref": "parity-run:expired", "signer_id": "operator-7",
        "key_id": "ops-ed25519-v1", "valid_from": "2026-08-01T00:00:00Z",
        "expires_at": "2026-08-02T00:00:00Z",
    }
    signature = base64.b64encode(private_key.sign(canonical_exception_bytes(payload))).decode()
    store_verified_exception(db, payload=payload, signature_b64=signature, public_key_bytes=public_key)
    report = allocation_shadow_parity_from_register(
        db, tenant_id="t1", case_id="order-expired",
        key_resolver=lambda _tenant, _key: public_key,
        as_of=datetime(2026, 8, 3, tzinfo=timezone.utc), persist=False,
    )

    assert report["parity_exception_verification"]["accepted"] == []
    assert report["parity_exception_verification"]["rejected"][0]["reason"] == "outside_validity_window"


def test_tampered_parity_exception_cannot_be_stored():
    db = _db()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    payload = {
        "tenant_id": "t1", "case_id": "order-tamper", "sku": "SKU-1",
        "difference_code": "shadow_quantity_higher",
        "rationale": "The signed evidence explains one bounded semantic difference.",
        "evidence_ref": "parity-run:tamper", "signer_id": "operator-7",
        "key_id": "ops-ed25519-v1", "valid_from": "2026-08-03T00:00:00Z",
        "expires_at": "2026-08-10T00:00:00Z",
    }
    signature = base64.b64encode(private_key.sign(canonical_exception_bytes(payload))).decode()
    payload["difference_code"] = "legacy_quantity_higher"

    with pytest.raises(ValueError, match="invalid_parity_exception_signature"):
        store_verified_exception(
            db, payload=payload, signature_b64=signature, public_key_bytes=public_key,
        )


def test_supplier_partial_schedule_persists_and_recomputes_buyer_promise_idempotently():
    db = _db()
    demand = _demand(db, "supplier-partial", stage="committed", qty=10)
    _snapshot(db, qty=4)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")
    args = dict(
        tenant_id="t1", demand_id=demand["id"], supplier_id="SUP-1", evidence_id="reply-1",
        schedule_lines=[{"status": "partial", "quantity": 3, "eta": "2026-08-10"},
                        {"status": "rejected", "quantity": 3}],
        observed_at="2026-08-02T00:10:00Z",
    )

    first = apply_supplier_schedule(db, **args)
    replay = apply_supplier_schedule(db, **args)

    assert first["promise_state"] == "partial"
    assert first["covered_qty"] == 7 and first["shortfall_qty"] == 3
    assert replay["promise_version"] == first["promise_version"]
    assert db.execute(text("SELECT COUNT(*) FROM supplier_schedule_allocation")).scalar() == 2
    promise = db.execute(text(
        "SELECT promise_state,covered_quantity,shortfall_quantity,alternatives_required "
        "FROM buyer_supply_promise"
    )).fetchone()
    assert tuple(promise) == ("partial", 7, 3, 1)
    view = allocation_workbench(db, tenant_id="t1", sku="SKU-1")
    assert view["summary"]["supplier_confirmed_quantity"] == 3
    assert view["summary"]["supplier_unresolved_quantity"] == 3


def test_workbench_anonymizes_buyers_and_reports_pressure_queue_and_child_count():
    db = _db()
    _demand(db, "workbench-1", stage="committed", qty=5)
    _snapshot(db, qty=2)
    allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")
    consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1", window_ends_at="2026-08-02T01:00:00Z"
    )

    view = allocation_workbench(db, tenant_id="t1", sku="SKU-1")

    assert view["summary"]["committed_quantity"] == 5
    assert view["summary"]["allocated_quantity"] == 2
    assert view["summary"]["shortfall_quantity"] == 3
    assert view["summary"]["supplier_confirmed_quantity"] == 0
    assert view["summary"]["supplier_unresolved_quantity"] == 0
    assert view["summary"]["allocation_pressure"] == 0.6
    evidence = view["metric_evidence"]
    assert evidence["allocation_pressure"]["formula"] == "shortfall_quantity / committed_quantity"
    assert evidence["allocation_pressure"]["numerator"] == 3
    assert evidence["allocation_pressure"]["denominator"] == 5
    assert evidence["allocation_pressure"]["authority"] == "shadow_allocation"
    assert evidence["allocation_pressure"]["source_record_count"] == 1
    assert evidence["allocation_pressure"]["trend_status"] == "not_materialized"
    assert evidence["allocated_quantity"]["source"] == "demand_allocation"
    assert evidence["supplier_unresolved_quantity"]["source"] == "buyer_supply_promise"
    assert view["sourcing_batches"][0]["child_demand_count"] == 1
    assert view["privacy"]["buyer_identities_exposed"] is False
    assert "buyer" not in view["demands"][0]


def test_workbench_resolves_order_identity_to_fulfillment_case_consequences():
    db = _db()
    demand = _demand(db, "order-trace-1", stage="committed", qty=5)
    db.execute(text(
        "UPDATE demand_commitment SET case_id='order-trace-1' WHERE id=:id"
    ), {"id": demand["id"]})
    db.execute(text("""CREATE TABLE fulfillment_case_version (
      id TEXT PRIMARY KEY,case_id TEXT,tenant_id TEXT,state_json TEXT,valid_to TEXT)"""))
    db.execute(text("""CREATE TABLE promise_calculation (
      id TEXT PRIMARY KEY,tenant_id TEXT,case_id TEXT,option_id TEXT,calculation_version TEXT,
      requested_quantity INTEGER,requested_arrival_at TEXT,feasibility TEXT,confirmed_quantity INTEGER,
      unknown_quantity INTEGER,quantity_by_deadline INTEGER,latest_viable_response_at TEXT,
      earliest_arrival_at TEXT,latest_arrival_at TEXT,carrier_cutoff_at TEXT,dispatch_ready_at TEXT,
      evaluated_at TEXT,response_expectation_json TEXT,reason_codes_json TEXT,dependencies_json TEXT,
      status TEXT,calculated_at TEXT)"""))
    db.execute(text("""CREATE TABLE procurement_payment_consequence (
      id TEXT PRIMARY KEY,tenant_id TEXT,case_id TEXT,consequence_json TEXT,
      created_at TEXT,superseded_at TEXT)"""))
    db.execute(text(
        "INSERT INTO fulfillment_case_version "
        "(id,case_id,tenant_id,state_json,valid_to) VALUES "
        "('v1','fulfillment-1','t1',:state,NULL)"
    ), {"state": json.dumps({"order_group_id": "order-order-trace-1"})})
    db.execute(text("""INSERT INTO promise_calculation (
      id,tenant_id,case_id,option_id,calculation_version,requested_quantity,requested_arrival_at,
      feasibility,confirmed_quantity,unknown_quantity,quantity_by_deadline,evaluated_at,
      response_expectation_json,reason_codes_json,dependencies_json,status,calculated_at)
      VALUES ('p1','t1','fulfillment-1','buyer-commitment','promise-v1',5,
      'relative:2:business_days','unknown',0,5,0,'2026-08-06T00:00:00Z','{}','["calendar_required"]',
      '{}','active','2026-08-06T00:00:00Z')"""))
    consequence = {
        "plan_type": "balance_after_confirmation", "status": "deposit_policy_required",
        "currency": "AUD", "total_amount_cents": 50000, "deposit_amount_cents": None,
        "balance_amount_cents": 50000, "state_prevented": "payment_authorization",
    }
    db.execute(text(
        "INSERT INTO procurement_payment_consequence "
        "(id,tenant_id,case_id,consequence_json,created_at,superseded_at) "
        "VALUES ('pay1','t1','fulfillment-1',:payload,'2026-08-06T00:00:00Z',NULL)"
    ), {"payload": json.dumps(consequence)})

    view = allocation_workbench(db, tenant_id="t1", sku="SKU-1")

    assert view["promise_calculation"]["feasibility"] == "unknown"
    assert view["promise_calculation"]["requested_arrival_at"] == "relative:2:business_days"
    assert view["payment_consequence"] == consequence


def test_workbench_projects_fresh_supplier_pressure_and_response_sla():
    db = _db()
    observed = datetime.now(timezone.utc) - timedelta(hours=1)
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    _demand(db, "supplier-pressure", stage="committed", qty=5)
    batches = consolidate_shortfalls(
        db, tenant_id="t1", supplier_id="SUP-1", window_ends_at="2100-08-03T18:00:00Z"
    )
    create_sourcing_wave(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        currency="AUD", incoterm="DAP", merchant_destination_id="SYD",
        window_ends_at="2100-08-03T18:00:00Z", batch_ids=[batches[0]["id"]],
        standalone_freight_cents=12000, consolidated_freight_cents=9000,
        handling_cents=1000,
    )
    persist_sourcing_policy(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        policy_version="v1", max_open_requests=4, max_open_units=100,
        max_request_units=50, max_dispatches_per_hour=3,
        acknowledgement_sla_seconds=7200, effective_from="2026-08-03T00:00:00Z",
    )
    record_sourcing_queue_observation(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        source_id="portal-adapter", source_version="snapshot-7",
        observed_at=observed, expires_at=expires,
        open_requests=3, open_units=80, dispatches_last_hour=2,
        oldest_unacknowledged_at=observed - timedelta(hours=1),
    )

    pressure = allocation_workbench(db, tenant_id="t1")["supplier_pressure"][0]

    assert pressure["supplier_id"] == "SUP-1"
    assert pressure["supplier_facility_id"] == "FAC-1"
    assert pressure["status"] == "watch"
    assert pressure["response_sla"]["status"] == "within_sla"
    assert pressure["queue"]["open_unit_utilization"] == 0.8
    assert pressure["source_health"]["status"] == "fresh"
    assert pressure["external_contact_authority"] == "governed"


def test_stale_supplier_queue_is_degraded_and_cannot_authorize_contact():
    db = _db()
    persist_sourcing_policy(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        policy_version="v1", max_open_requests=4, max_open_units=100,
        max_request_units=50, max_dispatches_per_hour=3,
        acknowledgement_sla_seconds=7200, effective_from="2026-08-03T00:00:00Z",
    )
    record_sourcing_queue_observation(
        db, tenant_id="t1", supplier_id="SUP-1", supplier_facility_id="FAC-1",
        source_id="portal-adapter", source_version="snapshot-old",
        observed_at="2026-08-01T12:00:00Z", expires_at="2026-08-01T12:05:00Z",
        open_requests=0, open_units=0, dispatches_last_hour=0,
    )

    from src.app.services.supplier_sourcing_authority import supplier_pressure_projection

    pressure = supplier_pressure_projection(
        db, tenant_id="t1", supplier_refs=[("SUP-1", "FAC-1")],
        now=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )[0]
    assert pressure["status"] == "degraded"
    assert pressure["source_health"]["status"] == "stale"
    assert pressure["external_contact_authority"] == "blocked"
