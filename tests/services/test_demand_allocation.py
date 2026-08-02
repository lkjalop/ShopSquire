import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.demand_allocation import (
    allocate_committed,
    allocation_shadow_parity,
    allocation_workbench,
    apply_supplier_schedule,
    commit_demand,
    consolidate_shortfalls,
    project_committed_order_demand,
    record_demand,
    sync_provisional_cart_demand,
    sync_authoritative_location_atp,
    transition_demand,
    upsert_supply_snapshot,
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
    assert view["sourcing_batches"][0]["child_demand_count"] == 1
    assert view["privacy"]["buyer_identities_exposed"] is False
    assert "buyer" not in view["demands"][0]
