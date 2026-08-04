"""Deterministic demand authority, allocation conservation, and RFQ consolidation.

The module owns no inventory truth. It consumes versioned ATP snapshots and projects bounded
allocations. Provisional demand is visible but never allocatable; committed demand is ordered by
priority tier, age, then stable id. All writes are tenant scoped and idempotent.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import inspect, text

from src.app.services.sourcing_backpressure import (
    SourcingBackpressurePolicy,
    SourcingQueueState,
    evaluate_sourcing_admission,
)
from src.app.services.supplier_sourcing_authority import supplier_pressure_projection


DEMAND_STAGES = frozenset({"provisional", "committed", "cancelled", "fulfilled"})
PARITY_DIFFERENCE_CODES = frozenset({
    "unallocated_committed_demand",
    "shadow_only_allocation",
    "legacy_only_reservation",
    "shadow_quantity_higher",
    "legacy_quantity_higher",
})
_ALLOWED_TRANSITIONS = {
    "provisional": frozenset({"committed", "cancelled"}),
    "committed": frozenset({"cancelled", "fulfilled"}),
    "cancelled": frozenset(),
    "fulfilled": frozenset(),
}


def priority_from_policy(*, demand_class: str, expedited: bool = False) -> int:
    """Closed priority policy; callers cannot submit arbitrary queue rank."""
    tiers = {"safety_critical": 10, "contractual": 20, "standard": 50, "speculative": 90}
    base = tiers.get(str(demand_class or "").strip().lower())
    if base is None:
        raise ValueError("unknown_demand_class")
    return max(1, base - 5) if expedited and base < 90 else base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_DEMAND_COLUMNS = (
    "id", "tenant_id", "idempotency_key", "case_id", "buyer_ref_hash", "sku", "uom",
    "destination_id", "stage", "quantity", "priority_tier", "required_by", "created_at",
    "updated_at", "fulfillment_location_id",
)
_BATCH_COLUMNS = (
    "id", "tenant_id", "idempotency_key", "consolidation_key", "sku", "uom",
    "destination_id", "supplier_id", "status", "quantity", "speculative_quantity",
    "window_ends_at", "created_at",
)


def _row_dict(row, columns: tuple[str, ...] = ()) -> dict[str, Any]:
    """Normalize SQLAlchemy Rows and the repository's sqlite tuple adapter.

    Production sessions return ``Row._mapping`` while the local compatibility DB deliberately
    exposes plain tuples. Treating only one as valid made the shadow projection degrade in the
    actual recording stack despite passing the isolated SQLAlchemy tests.
    """
    if row is None:
        return {}
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return dict(mapping)
    return dict(zip(columns, tuple(row))) if columns else {}


def record_demand(
    db,
    *,
    tenant_id: str,
    idempotency_key: str,
    sku: str,
    quantity: int,
    destination_id: str,
    stage: str = "provisional",
    uom: str = "each",
    priority_tier: int = 100,
    case_id: str | None = None,
    buyer_ref_hash: str | None = None,
    required_by: str | None = None,
    fulfillment_location_id: str | None = None,
) -> dict[str, Any]:
    """Append one authoritative demand identity; replay returns the original row."""
    stage = str(stage).lower()
    if stage not in DEMAND_STAGES:
        raise ValueError("invalid_demand_stage")
    if int(quantity) <= 0:
        raise ValueError("quantity_must_be_positive")
    existing = db.execute(text(
        "SELECT * FROM demand_commitment WHERE tenant_id=:t AND idempotency_key=:k"
    ), {"t": tenant_id, "k": idempotency_key}).fetchone()
    if existing:
        return {**_row_dict(existing, _DEMAND_COLUMNS), "idempotent": True}
    demand_id = str(uuid.uuid4())
    db.execute(text(
        "INSERT INTO demand_commitment "
        "(id,tenant_id,idempotency_key,case_id,buyer_ref_hash,sku,uom,destination_id,stage,"
        "quantity,priority_tier,required_by,created_at,updated_at,fulfillment_location_id) VALUES "
        "(:id,:t,:k,:case_id,:buyer,:sku,:uom,:dest,:stage,:qty,:priority,:required_by,:now,:now,:loc)"
    ), {"id": demand_id, "t": tenant_id, "k": idempotency_key, "case_id": case_id,
        "buyer": buyer_ref_hash, "sku": sku, "uom": uom, "dest": destination_id,
        "stage": stage, "qty": int(quantity), "priority": int(priority_tier),
        "required_by": required_by, "now": _now(), "loc": fulfillment_location_id})
    row = db.execute(text("SELECT * FROM demand_commitment WHERE id=:id"), {"id": demand_id}).fetchone()
    return {**_row_dict(row, _DEMAND_COLUMNS), "idempotent": False}


def commit_demand(db, *, tenant_id: str, demand_id: str) -> dict[str, Any]:
    """Promote provisional visibility to commitment; cancelled demand cannot be resurrected."""
    result = db.execute(text(
        "UPDATE demand_commitment SET stage='committed', updated_at=:now "
        "WHERE id=:id AND tenant_id=:t AND stage='provisional'"
    ), {"id": demand_id, "t": tenant_id, "now": _now()})
    row = db.execute(text(
        "SELECT * FROM demand_commitment WHERE id=:id AND tenant_id=:t"
    ), {"id": demand_id, "t": tenant_id}).fetchone()
    if row is None:
        raise KeyError("demand_not_found")
    value = _row_dict(row, _DEMAND_COLUMNS)
    return {**value, "changed": bool(getattr(result, "rowcount", 0)),
            "state_prevented": None if value.get("stage") == "committed" else "illegal_stage_transition"}


def transition_demand(db, *, tenant_id: str, demand_id: str, target_stage: str) -> dict[str, Any]:
    """Apply a closed lifecycle transition and release/consume allocations atomically."""
    target = str(target_stage or "").lower()
    if target not in DEMAND_STAGES or target == "provisional":
        raise ValueError("invalid_demand_target_stage")
    row = db.execute(text(
        "SELECT * FROM demand_commitment WHERE id=:id AND tenant_id=:t"
    ), {"id": demand_id, "t": tenant_id}).fetchone()
    if row is None:
        raise KeyError("demand_not_found")
    current = str(_row_dict(row, _DEMAND_COLUMNS)["stage"])
    current_version = str(_row_dict(row, _DEMAND_COLUMNS).get("updated_at") or "unknown")
    if target == current:
        return {**_row_dict(row, _DEMAND_COLUMNS), "changed": False, "idempotent": True}
    if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        return {**_row_dict(row, _DEMAND_COLUMNS), "changed": False,
                "state_prevented": f"illegal_transition:{current}->{target}"}
    db.execute(text(
        "UPDATE demand_commitment SET stage=:stage,updated_at=:now WHERE id=:id AND tenant_id=:t"
    ), {"stage": target, "now": _now(), "id": demand_id, "t": tenant_id})
    allocation_state = "released" if target == "cancelled" else "consumed"
    if target in {"cancelled", "fulfilled"}:
        db.execute(text(
            "UPDATE demand_allocation SET status=:status WHERE tenant_id=:t "
            "AND demand_id=:id AND status='allocated'"
        ), {"status": allocation_state, "t": tenant_id, "id": demand_id})
        from src.app.services.temporal_invalidation import invalidate_source_dependencies

        invalidate_source_dependencies(
            db, tenant_id=tenant_id, source_type="committed_demand", source_id=demand_id,
            source_version=current_version, reason=f"demand_transition:{current}->{target}",
        )
    updated = db.execute(text(
        "SELECT * FROM demand_commitment WHERE id=:id AND tenant_id=:t"
    ), {"id": demand_id, "t": tenant_id}).fetchone()
    return {**_row_dict(updated, _DEMAND_COLUMNS), "changed": True, "allocation_state": allocation_state}


def sync_provisional_cart_demand(db, *, tenant_id: str, cart_id: str,
                                 buyer_ref_hash: str, items: Iterable[dict[str, Any]],
                                 destination_id: str = "destination-unset") -> dict[str, Any]:
    """Project a cart as provisional visibility; it never allocates supply."""
    desired = {
        str(item.get("sku")): int(item.get("quantity") or 0)
        for item in items if item.get("sku") and int(item.get("quantity") or 0) > 0
    }
    rows = db.execute(text(
        "SELECT id,sku,stage,quantity FROM demand_commitment "
        "WHERE tenant_id=:t AND case_id=:cart AND idempotency_key LIKE :prefix"
    ), {"t": tenant_id, "cart": cart_id, "prefix": f"cart:{cart_id}:%"}).fetchall()
    existing = {str(row[1]): row for row in rows}
    changed, prevented = [], []
    for sku, quantity in desired.items():
        row = existing.get(sku)
        if row is None:
            created = record_demand(
                db, tenant_id=tenant_id, idempotency_key=f"cart:{cart_id}:{sku}",
                sku=sku, quantity=quantity, destination_id=destination_id,
                stage="provisional", priority_tier=priority_from_policy(demand_class="standard"),
                case_id=cart_id, buyer_ref_hash=buyer_ref_hash,
            )
            changed.append({"sku": sku, "quantity": quantity, "demand_id": created["id"]})
        elif str(row[2]) == "provisional":
            if int(row[3]) != quantity:
                db.execute(text(
                    "UPDATE demand_commitment SET quantity=:qty,updated_at=:now WHERE id=:id"
                ), {"qty": quantity, "now": _now(), "id": row[0]})
                changed.append({"sku": sku, "quantity": quantity, "demand_id": str(row[0])})
        else:
            prevented.append({"sku": sku, "reason": f"cart_cannot_mutate_{row[2]}_demand"})
    for sku, row in existing.items():
        if sku not in desired and str(row[2]) == "provisional":
            transition_demand(db, tenant_id=tenant_id, demand_id=str(row[0]), target_stage="cancelled")
            changed.append({"sku": sku, "quantity": 0, "demand_id": str(row[0])})
    return {"status": "projected", "authority": "provisional", "changed": changed,
            "state_prevented": prevented, "allocates_supply": False}


def project_committed_order_demand(
    db,
    *,
    tenant_id: str,
    order_id: str,
    buyer_ref_hash: str,
    lines: Iterable[dict[str, Any]],
    destination_id: str,
    required_by: str | None = None,
    amendment_version: str | None = None,
    default_fulfillment_location_id: str | None = None,
) -> dict[str, Any]:
    """Promote matching cart visibility, or create an idempotent committed shadow row.

    This records buyer authority but deliberately does not execute inventory allocation. The
    existing reservation path remains authoritative until PostgreSQL concurrency parity is
    certified. Replays return the same demand identities.
    """
    aggregated: dict[str, dict[str, Any]] = {}
    for line in lines:
        sku = str(line.get("item_ref") or line.get("sku") or "").strip()
        quantity = int(line.get("requested_qty") or line.get("quantity") or 0)
        availability = line.get("availability") if isinstance(line.get("availability"), dict) else {}
        location = str(
            line.get("fulfillment_location_id")
            or line.get("location_id")
            or availability.get("preferred_location_id")
            or availability.get("preferred_location")
            or default_fulfillment_location_id
            or ""
        ).strip() or None
        if sku and quantity > 0:
            entry = aggregated.setdefault(sku, {"quantity": 0, "location": location})
            entry["quantity"] += quantity
            if entry["location"] and location and entry["location"] != location:
                entry["location"] = None
    committed: list[dict[str, Any]] = []
    for sku, demand_input in sorted(aggregated.items()):
        quantity = int(demand_input["quantity"])
        fulfillment_location_id = demand_input["location"]
        if amendment_version:
            active_rows = db.execute(text(
                "SELECT id FROM demand_commitment WHERE tenant_id=:t AND case_id=:order "
                "AND sku=:sku AND stage='committed' ORDER BY created_at"
            ), {"t": tenant_id, "order": order_id, "sku": sku}).fetchall()
            for active in active_rows:
                transition_demand(
                    db, tenant_id=tenant_id, demand_id=str(active[0]), target_stage="cancelled"
                )
        provisional = db.execute(text(
            "SELECT * FROM demand_commitment WHERE tenant_id=:t AND case_id=:order "
            "AND sku=:sku AND stage='provisional' ORDER BY created_at LIMIT 1"
        ), {"t": tenant_id, "order": order_id, "sku": sku}).fetchone()
        if provisional is not None:
            row = _row_dict(provisional, _DEMAND_COLUMNS)
            db.execute(text(
                "UPDATE demand_commitment SET quantity=:qty,destination_id=:dest,"
                "fulfillment_location_id=:loc,"
                "required_by=:required,priority_tier=:priority,updated_at=:now "
                "WHERE id=:id AND tenant_id=:t AND stage='provisional'"
            ), {"qty": quantity, "dest": destination_id, "loc": fulfillment_location_id,
                "required": required_by,
                "priority": priority_from_policy(demand_class="standard"), "now": _now(),
                "id": row["id"], "t": tenant_id})
            promoted = commit_demand(db, tenant_id=tenant_id, demand_id=str(row["id"]))
            committed.append({**promoted, "source_stage": "provisional"})
            continue
        version_suffix = f":amendment:{amendment_version}" if amendment_version else ""
        created = record_demand(
            db,
            tenant_id=tenant_id,
            idempotency_key=f"order:{order_id}{version_suffix}:{sku}",
            sku=sku,
            quantity=quantity,
            destination_id=destination_id,
            stage="committed",
            priority_tier=priority_from_policy(demand_class="standard"),
            case_id=order_id,
            buyer_ref_hash=buyer_ref_hash,
            required_by=required_by,
            fulfillment_location_id=fulfillment_location_id,
        )
        committed.append({**created, "source_stage": "order_confirmation"})
    return {
        "status": "projected",
        "authority": "buyer_committed",
        "demands": committed,
        "allocates_supply": False,
        "execution_path": "legacy_inventory_reservations_until_parity",
        "amendment_version": amendment_version,
    }


def upsert_supply_snapshot(db, *, tenant_id: str, sku: str, uom: str, location_id: str,
                           atp_quantity: int, snapshot_version: str, observed_at: str,
                           expires_at: str | None = None, source_id: str | None = None,
                           source_authority: str = "unknown", completeness: str = "unknown",
                           source_observation_id: str | None = None) -> dict[str, Any]:
    """CAS one location ATP snapshot; an older feed can never overwrite newer supply truth."""
    if int(atp_quantity) < 0:
        raise ValueError("atp_must_be_nonnegative")
    existing = db.execute(text(
        "SELECT observed_at,snapshot_version,source_observation_id FROM supply_allocation_pool "
        "WHERE tenant_id=:t AND sku=:sku AND uom=:uom AND location_id=:loc"
    ), {"t": tenant_id, "sku": sku, "uom": uom, "loc": location_id}).fetchone()
    if existing and _parse_timestamp(str(existing[0])) > _parse_timestamp(observed_at):
        return {"status": "superseded", "snapshot_version": str(existing[1]),
                "state_prevented": "older_atp_snapshot"}
    if existing and str(existing[1]) != str(snapshot_version):
        from src.app.services.temporal_invalidation import invalidate_source_dependencies

        invalidate_source_dependencies(
            db, tenant_id=tenant_id, source_type="location_atp",
            source_id=str(existing[2] or f"{sku}:{uom}:{location_id}"),
            source_version=str(existing[1]), reason=f"superseded_by:{snapshot_version}",
        )
    updated = db.execute(text(
        "UPDATE supply_allocation_pool SET atp_quantity=:qty,snapshot_version=:version,"
        "observed_at=:observed,expires_at=:expires,source_id=:source,"
        "source_authority=:authority,completeness=:completeness,"
        "source_observation_id=:observation WHERE tenant_id=:t AND sku=:sku "
        "AND uom=:uom AND location_id=:loc"
    ), {"qty": int(atp_quantity), "version": snapshot_version, "observed": observed_at,
        "expires": expires_at, "source": source_id, "authority": source_authority,
        "completeness": completeness, "observation": source_observation_id,
        "t": tenant_id, "sku": sku, "uom": uom, "loc": location_id})
    if not getattr(updated, "rowcount", 0):
        db.execute(text(
            "INSERT INTO supply_allocation_pool "
            "(tenant_id,sku,uom,location_id,atp_quantity,snapshot_version,observed_at,expires_at,"
            "source_id,source_authority,completeness,source_observation_id) "
            "VALUES (:t,:sku,:uom,:loc,:qty,:version,:observed,:expires,:source,:authority,"
            ":completeness,:observation)"
        ), {"t": tenant_id, "sku": sku, "uom": uom, "loc": location_id,
            "qty": int(atp_quantity), "version": snapshot_version, "observed": observed_at,
            "expires": expires_at, "source": source_id, "authority": source_authority,
            "completeness": completeness, "observation": source_observation_id})
    return {"status": "applied", "snapshot_version": snapshot_version,
            "source_authority": source_authority, "completeness": completeness}


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def sync_authoritative_location_atp(db, *, tenant_id: str, source: str,
                                    now: datetime | None = None) -> dict[str, Any]:
    """Project accepted canonical ``location_atp`` observations into the allocation pool.

    The append-only business feed remains the fact authority. This disposable pool records the exact
    observation id/version, completeness and expiry that allocation consumed.
    """
    from src.app.services.business_semantics import LocationATPPayload, project_atp

    tenant = str(tenant_id or "").strip()
    source_id = str(source or "").strip().lower()
    if not tenant or not source_id:
        raise ValueError("authoritative_atp_scope_required")
    rows = db.execute(text(
        "SELECT id,event_time,payload_json,feed_run_id,event_kind,reverses_observation_id "
        "FROM authoritative_business_observation "
        "WHERE tenant_id=:t AND source=:source AND entity_type='location_atp' "
        "AND quality_status='accepted' ORDER BY event_time DESC,id DESC"
    ), {"t": tenant, "source": source_id}).fetchall()
    reversed_ids = {str(row[5]) for row in rows if row[5]}
    latest: dict[tuple[str, str, str], tuple[Any, ...]] = {}
    rejected: list[dict[str, str]] = []
    for row in rows:
        if str(row[4] or "observation") == "reversal" or str(row[0]) in reversed_ids:
            continue
        try:
            payload = LocationATPPayload.model_validate(json.loads(str(row[2])))
            projected = project_atp(payload, now=now)
            key = (payload.variant_id, payload.location_id,
                   str((payload.source_atp or payload.on_hand).uom))
            latest.setdefault(key, (row, payload, projected))
        except Exception as exc:
            rejected.append({"observation_id": str(row[0]), "reason": type(exc).__name__})
    applied: list[dict[str, Any]] = []
    current = now or datetime.now(timezone.utc)
    for (sku, location_id, uom), (row, payload, projected) in latest.items():
        if projected.get("quantity") is None:
            rejected.append({"observation_id": str(row[0]), "reason": "atp_unavailable"})
            continue
        calculated = _parse_timestamp(payload.source_calculated_at)
        expires_at = (calculated + timedelta(seconds=int(payload.ttl_seconds))).isoformat()
        quantity = Decimal(str(projected["quantity"]))
        if quantity != quantity.to_integral_value():
            rejected.append({"observation_id": str(row[0]),
                             "reason": "fractional_atp_requires_uom_conversion"})
            continue
        result = upsert_supply_snapshot(
            db, tenant_id=tenant, sku=sku, uom=uom, location_id=location_id,
            atp_quantity=int(quantity),
            snapshot_version=str(row[3] or row[0]), observed_at=calculated.isoformat(),
            expires_at=expires_at, source_id=source_id, source_authority="authoritative",
            completeness=str(projected["completeness"]), source_observation_id=str(row[0]),
        )
        applied.append({"sku": sku, "location_id": location_id, "uom": uom,
                        "freshness": projected["status"], "age_seconds": projected["age_seconds"],
                        **result})
    return {"tenant_id": tenant, "source": source_id, "as_of": current.isoformat(),
            "status": "ready" if applied and not rejected else "degraded" if applied else "insufficient",
            "applied": applied, "rejected": rejected}


def allocate_committed(db, *, tenant_id: str, sku: str, uom: str = "each",
                       location_id: str) -> dict[str, Any]:
    """Allocate without stealing: existing allocations stand; remaining ATP follows stable priority."""
    # PostgreSQL serializes allocators on the authoritative pool row. SQLite obtains its write lock
    # on the first mutation and does not accept FOR UPDATE; the deterministic contract tests use it
    # only as a protocol stand-in, not as concurrency certification.
    lock_suffix = " FOR UPDATE" if db.get_bind().dialect.name == "postgresql" else ""
    pool = db.execute(text(
        "SELECT atp_quantity,snapshot_version,expires_at,source_authority,completeness,"
        "observed_at,source_observation_id FROM supply_allocation_pool "
        "WHERE tenant_id=:t AND sku=:sku AND uom=:uom AND location_id=:loc" + lock_suffix
    ), {"t": tenant_id, "sku": sku, "uom": uom, "loc": location_id}).fetchone()
    if pool is None:
        return {"status": "unknown_supply", "allocated": [], "available": None}
    if pool[2]:
        try:
            if datetime.fromisoformat(str(pool[2]).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                return {"status": "stale_supply", "allocated": [], "available": None,
                        "snapshot_version": str(pool[1])}
        except ValueError:
            return {"status": "invalid_supply_expiry", "allocated": [], "available": None}
    atp = int(pool[0] or 0)
    if str(pool[3] or "") != "authoritative":
        return {"status": "non_authoritative_supply", "allocated": [], "available": None,
                "snapshot_version": str(pool[1]), "source_authority": str(pool[3] or "unknown")}
    if str(pool[4] or "") == "incomplete":
        return {"status": "incomplete_supply", "allocated": [], "available": None,
                "snapshot_version": str(pool[1])}
    used = int(db.execute(text(
        "SELECT COALESCE(SUM(quantity),0) FROM demand_allocation WHERE tenant_id=:t AND sku=:sku "
        "AND uom=:uom AND location_id=:loc AND status='allocated'"
    ), {"t": tenant_id, "sku": sku, "uom": uom, "loc": location_id}).scalar() or 0)
    remaining = max(0, atp - used)
    rows = db.execute(text(
        "SELECT d.id,d.quantity,d.priority_tier,d.created_at,"
        "COALESCE((SELECT SUM(a.quantity) FROM demand_allocation a WHERE a.demand_id=d.id "
        "AND a.status='allocated'),0) AS allocated_qty "
        "FROM demand_commitment d WHERE d.tenant_id=:t AND d.sku=:sku AND d.uom=:uom "
        "AND d.fulfillment_location_id=:loc AND d.stage='committed' "
        "ORDER BY d.priority_tier ASC,d.created_at ASC,d.id ASC"
    ), {"t": tenant_id, "sku": sku, "uom": uom, "loc": location_id}).fetchall()
    added: list[dict[str, Any]] = []
    for demand_id, quantity, tier, _created, already in rows:
        need = max(0, int(quantity) - int(already or 0))
        take = min(need, remaining)
        if take <= 0:
            continue
        if int(already or 0) > 0:
            db.execute(text(
                "UPDATE demand_allocation SET quantity=quantity+:qty WHERE tenant_id=:t "
                "AND demand_id=:d AND location_id=:loc AND status='allocated'"
            ), {"qty": take, "t": tenant_id, "d": demand_id, "loc": location_id})
        else:
            allocation_id = str(uuid.uuid4())
            db.execute(text(
                "INSERT INTO demand_allocation "
                "(id,tenant_id,demand_id,sku,uom,location_id,quantity,status,created_at) "
                "VALUES (:id,:t,:d,:sku,:uom,:loc,:qty,'allocated',:now)"
            ), {"id": allocation_id, "t": tenant_id, "d": demand_id, "sku": sku,
                "uom": uom, "loc": location_id, "qty": take, "now": _now()})
        from src.app.services.temporal_invalidation import register_derived_dependency

        register_derived_dependency(
            db, tenant_id=tenant_id, source_type="location_atp",
            source_id=str(pool[6] or f"{sku}:{uom}:{location_id}"),
            source_version=str(pool[1]), derived_type="allocation_projection",
            derived_id=f"{demand_id}:{location_id}",
        )
        added.append({"demand_id": demand_id, "quantity": take, "priority_tier": int(tier)})
        remaining -= take
    return {"status": "allocated", "snapshot_version": str(pool[1]), "atp": atp,
            "freshness": "current", "observed_at": str(pool[5]),
            "source_observation_id": str(pool[6] or ""),
            "previously_allocated": used, "allocated": added, "remaining": remaining,
            "conservation_ok": used + sum(x["quantity"] for x in added) <= atp}


def consolidate_shortfalls(db, *, tenant_id: str, supplier_id: str | None,
                           window_ends_at: str, urgency_bypass: bool = False,
                           max_open_batches: int = 100,
                           max_batch_quantity: int = 10_000,
                           backpressure_policy: SourcingBackpressurePolicy | None = None,
                           supplier_queue_state: SourcingQueueState | None = None,
                           ) -> list[dict[str, Any]]:
    """Create one draft batch per compatible committed shortfall and retain every child demand."""
    rows = db.execute(text(
        "SELECT d.id,d.sku,d.uom,d.destination_id,d.quantity,"
        "COALESCE((SELECT SUM(a.quantity) FROM demand_allocation a WHERE a.demand_id=d.id "
        "AND a.status='allocated'),0) AS allocated_qty "
        "FROM demand_commitment d WHERE d.tenant_id=:t AND d.stage='committed' "
        "ORDER BY d.sku,d.uom,d.destination_id,d.id"
    ), {"t": tenant_id}).fetchall()
    grouped: dict[tuple[str, str, str], list[tuple[str, int]]] = {}
    for demand_id, sku, uom, destination, quantity, allocated in rows:
        shortfall = max(0, int(quantity) - int(allocated or 0))
        if shortfall:
            grouped.setdefault((str(sku), str(uom), str(destination)), []).append(
                (str(demand_id), shortfall)
            )
    out = []
    for (sku, uom, destination), children in grouped.items():
        child_signature = sorted(children)
        base_key = f"{sku}|{uom}|{destination}|{supplier_id or 'unassigned'}"
        consolidation_key = (
            f"{base_key}|urgent|{child_signature[0][0]}" if urgency_bypass else base_key
        )
        material = {"tenant": tenant_id, "key": consolidation_key,
                    "window": window_ends_at, "urgent": bool(urgency_bypass)}
        idem = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        existing = db.execute(text(
            "SELECT * FROM sourcing_batch WHERE tenant_id=:t AND consolidation_key=:key "
            "AND window_ends_at=:window AND status='draft' ORDER BY created_at LIMIT 1"
        ), {"t": tenant_id, "key": consolidation_key, "window": window_ends_at}).fetchone()
        if existing:
            batch = _row_dict(existing, _BATCH_COLUMNS)
            added = []
            for demand_id, quantity in children:
                child = db.execute(text(
                    "SELECT quantity FROM sourcing_batch_demand WHERE batch_id=:batch AND demand_id=:demand"
                ), {"batch": batch["id"], "demand": demand_id}).fetchone()
                if child:
                    continue
                if int(batch.get("quantity") or 0) + sum(q for _d, q in added) + quantity > max_batch_quantity:
                    break
                db.execute(text(
                    "INSERT INTO sourcing_batch_demand (batch_id,demand_id,quantity) "
                    "VALUES (:batch,:demand,:qty)"
                ), {"batch": batch["id"], "demand": demand_id, "qty": quantity})
                added.append((demand_id, quantity))
            if added:
                increment = sum(quantity for _demand, quantity in added)
                db.execute(text(
                    "UPDATE sourcing_batch SET quantity=quantity+:qty WHERE id=:id"
                ), {"qty": increment, "id": batch["id"]})
                batch["quantity"] = int(batch.get("quantity") or 0) + increment
            out.append({**batch, "idempotent": not bool(added), "children_appended": added})
            continue
        open_count = int(db.execute(text(
            "SELECT COUNT(*) FROM sourcing_batch WHERE tenant_id=:t AND status='draft'"
        ), {"t": tenant_id}).scalar() or 0)
        total = sum(quantity for _demand, quantity in children)
        if backpressure_policy is not None:
            if supplier_queue_state is None:
                raise ValueError("supplier_queue_state_required_for_backpressure_policy")
            admission = evaluate_sourcing_admission(
                policy=backpressure_policy,
                state=supplier_queue_state,
                requested_units=total,
                compatible_open_request=False,
                urgent=urgency_bypass,
            )
            if admission.action != "open_request":
                out.append({
                    "status": "blocked",
                    "reason": "supplier_backpressure",
                    "admission_action": admission.action,
                    "reason_codes": list(admission.reason_codes),
                    "next_permitted_actions": list(admission.next_permitted_actions),
                    "external_contact_permitted": admission.external_contact_permitted,
                    "sku": sku,
                    "quantity": total,
                })
                continue
        if open_count >= max_open_batches:
            out.append({"status": "blocked", "reason": "operator_queue_limit",
                        "sku": sku, "quantity": total})
            continue
        if total > max_batch_quantity:
            out.append({"status": "blocked", "reason": "supplier_capacity_limit",
                        "sku": sku, "quantity": total})
            continue
        batch_id = str(uuid.uuid4())
        db.execute(text(
            "INSERT INTO sourcing_batch "
            "(id,tenant_id,idempotency_key,consolidation_key,sku,uom,destination_id,supplier_id,"
            "status,quantity,speculative_quantity,window_ends_at,created_at) VALUES "
            "(:id,:t,:idem,:key,:sku,:uom,:dest,:supplier,'draft',:qty,0,:window,:now)"
        ), {"id": batch_id, "t": tenant_id, "idem": idem, "key": consolidation_key,
            "sku": sku, "uom": uom, "dest": destination, "supplier": supplier_id,
            "qty": total, "window": window_ends_at, "now": _now()})
        for demand_id, quantity in children:
            db.execute(text(
                "INSERT INTO sourcing_batch_demand (batch_id,demand_id,quantity) "
                "VALUES (:batch,:demand,:qty)"
            ), {"batch": batch_id, "demand": demand_id, "qty": quantity})
        out.append({"id": batch_id, "tenant_id": tenant_id, "sku": sku, "uom": uom,
                    "destination_id": destination, "supplier_id": supplier_id, "quantity": total,
                    "speculative_quantity": 0, "status": "draft", "children": child_signature,
                    "idempotent": False})
    return out


def create_sourcing_wave(
    db,
    *,
    tenant_id: str,
    supplier_id: str,
    supplier_facility_id: str,
    currency: str,
    incoterm: str,
    merchant_destination_id: str,
    window_ends_at: str,
    batch_ids: Iterable[str],
    standalone_freight_cents: int,
    consolidated_freight_cents: int,
    handling_cents: int = 0,
) -> dict[str, Any]:
    """Group compatible SKU batches beneath one supplier/facility shipment authority.

    A wave is an economic and logistics proposal only.  Child batches retain quantity authority,
    and creation neither sends an RFQ nor creates a purchase order.
    """
    ids = sorted({str(value).strip() for value in batch_ids if str(value).strip()})
    if not ids:
        return {"status": "blocked", "state_prevented": "empty_sourcing_wave"}
    costs = [int(standalone_freight_cents), int(consolidated_freight_cents), int(handling_cents)]
    if any(value < 0 for value in costs):
        raise ValueError("negative_freight_cost")
    placeholders = ",".join(f":b{i}" for i in range(len(ids)))
    params: dict[str, Any] = {"t": tenant_id, **{f"b{i}": value for i, value in enumerate(ids)}}
    rows = db.execute(text(
        "SELECT id,sku,uom,destination_id,supplier_id,status,quantity FROM sourcing_batch "
        f"WHERE tenant_id=:t AND id IN ({placeholders}) ORDER BY id"
    ), params).fetchall()
    if len(rows) != len(ids) or any(
        str(row[4] or "") != str(supplier_id)
        or str(row[3]) != str(merchant_destination_id)
        or str(row[5]) != "draft"
        for row in rows
    ):
        return {"status": "blocked", "state_prevented": "incompatible_sourcing_batch"}
    already = db.execute(text(
        "SELECT w.id,w.status,w.estimated_savings_cents FROM sourcing_wave w "
        "JOIN sourcing_wave_batch wb ON wb.wave_id=w.id WHERE w.tenant_id=:t "
        f"AND wb.batch_id IN ({placeholders}) ORDER BY w.created_at LIMIT 1"
    ), params).fetchone()
    if already:
        count = int(db.execute(text(
            "SELECT COUNT(*) FROM sourcing_wave_batch WHERE wave_id=:id"
        ), {"id": already[0]}).scalar() or 0)
        return {"wave_id": str(already[0]), "status": str(already[1]),
                "estimated_savings_cents": int(already[2]), "batch_count": count,
                "line_count": count, "idempotent": True, "external_action": "none"}
    material = {
        "tenant_id": tenant_id, "supplier_id": supplier_id,
        "supplier_facility_id": supplier_facility_id, "currency": currency.upper(),
        "incoterm": incoterm.upper(), "merchant_destination_id": merchant_destination_id,
        "window_ends_at": window_ends_at, "batch_ids": ids,
    }
    idem = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    savings = int(standalone_freight_cents) - int(consolidated_freight_cents) - int(handling_cents)
    wave_id = str(uuid.uuid4())
    now = _now()
    db.execute(text(
        "INSERT INTO sourcing_wave "
        "(id,tenant_id,idempotency_key,supplier_id,supplier_facility_id,currency,incoterm,"
        "merchant_destination_id,status,window_ends_at,standalone_freight_cents,"
        "consolidated_freight_cents,handling_cents,estimated_savings_cents,created_at,updated_at) "
        "VALUES (:id,:t,:idem,:supplier,:facility,:currency,:incoterm,:destination,'draft',"
        ":window,:standalone,:consolidated,:handling,:savings,:now,:now)"
    ), {"id": wave_id, "t": tenant_id, "idem": idem, "supplier": supplier_id,
        "facility": supplier_facility_id, "currency": currency.upper(),
        "incoterm": incoterm.upper(), "destination": merchant_destination_id,
        "window": window_ends_at, "standalone": int(standalone_freight_cents),
        "consolidated": int(consolidated_freight_cents), "handling": int(handling_cents),
        "savings": savings, "now": now})
    for batch_id in ids:
        db.execute(text(
            "INSERT INTO sourcing_wave_batch (wave_id,batch_id) VALUES (:wave,:batch)"
        ), {"wave": wave_id, "batch": batch_id})
    return {"wave_id": wave_id, "status": "draft", "supplier_id": supplier_id,
            "supplier_facility_id": supplier_facility_id, "currency": currency.upper(),
            "incoterm": incoterm.upper(), "merchant_destination_id": merchant_destination_id,
            "batch_count": len(ids), "line_count": len(rows),
            "total_quantity": sum(int(row[6]) for row in rows),
            "standalone_freight_cents": int(standalone_freight_cents),
            "consolidated_freight_cents": int(consolidated_freight_cents),
            "handling_cents": int(handling_cents), "estimated_savings_cents": savings,
            "idempotent": False, "external_action": "none"}


def allocation_shadow_parity(
    db,
    *,
    tenant_id: str,
    case_id: str | None = None,
    persist: bool = True,
    accepted_difference_codes: Iterable[str] = (),
    verified_difference_scopes: Iterable[dict[str, Any]] = (),
    parity_exception_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the new shadow allocations with the legacy reservation executor.

    Legacy rows have neither tenant nor location identity, so a report can prove quantity parity for
    a scoped order but can never certify tenant/location parity. That limitation is returned explicitly.
    """
    accepted = frozenset(str(code).strip() for code in accepted_difference_codes)
    unsupported = sorted(accepted - PARITY_DIFFERENCE_CODES)
    if unsupported:
        raise ValueError(
            "unsupported_parity_difference_code:" + ",".join(unsupported)
        )
    verified_scopes = tuple(dict(scope) for scope in verified_difference_scopes)
    unsupported_verified = sorted({
        str(scope.get("difference_code") or "") for scope in verified_scopes
        if str(scope.get("difference_code") or "") not in PARITY_DIFFERENCE_CODES
    })
    if unsupported_verified:
        raise ValueError(
            "unsupported_parity_difference_code:" + ",".join(unsupported_verified)
        )
    clause = " AND d.case_id=:case_id" if case_id else ""
    params: dict[str, Any] = {"t": tenant_id}
    if case_id:
        params["case_id"] = case_id
    new_rows = db.execute(text(
        "SELECT d.case_id,d.sku,d.quantity,COALESCE(SUM(a.quantity),0) "
        "FROM demand_commitment d LEFT JOIN demand_allocation a ON a.demand_id=d.id "
        "AND a.status='allocated' WHERE d.tenant_id=:t AND d.stage='committed'" + clause +
        " GROUP BY d.case_id,d.sku,d.quantity ORDER BY d.case_id,d.sku"
    ), params).fetchall()
    new_by_key = {(str(row[0] or ""), str(row[1])): {"committed": int(row[2]),
                                                       "allocated": int(row[3] or 0)}
                  for row in new_rows}
    legacy_by_key: dict[tuple[str, str], int] = {}
    limitations = ["legacy_reservations_not_tenant_scoped", "legacy_reservations_not_location_scoped"]
    try:
        legacy_rows = db.execute(text(
            "SELECT order_id,sku,COALESCE(SUM(qty),0) FROM inventory_reservations "
            "WHERE status='reserved'" + (" AND order_id=:case_id" if case_id else "") +
            " GROUP BY order_id,sku ORDER BY order_id,sku"
        ), ({"case_id": case_id} if case_id else {})).fetchall()
        legacy_by_key = {(str(row[0]), str(row[1])): int(row[2] or 0) for row in legacy_rows}
    except Exception:
        limitations.append("legacy_reservation_table_unavailable")
        db.rollback()
    keys = sorted(set(new_by_key) | set(legacy_by_key))
    comparisons = []
    for key in keys:
        new = new_by_key.get(key, {"committed": 0, "allocated": 0})
        legacy = legacy_by_key.get(key, 0)
        allocated = int(new["allocated"])
        quantity_match = allocated == int(legacy)
        difference_code = None
        if not quantity_match:
            if key not in legacy_by_key:
                difference_code = (
                    "shadow_only_allocation"
                    if allocated > 0
                    else "unallocated_committed_demand"
                )
            elif key not in new_by_key:
                difference_code = "legacy_only_reservation"
            elif allocated > int(legacy):
                difference_code = "shadow_quantity_higher"
            else:
                difference_code = "legacy_quantity_higher"
        signed_scope = next((scope for scope in verified_scopes if
            scope.get("difference_code") == difference_code
            and str(scope.get("sku") or "") in {"", key[1]}
        ), None)
        comparisons.append({
            "case_id": key[0], "sku": key[1], **new,
            "legacy_reserved": legacy, "quantity_match": quantity_match,
            "difference_code": difference_code,
            "difference_accepted": bool(difference_code in accepted or signed_scope),
            "parity_exception_id": signed_scope.get("id") if signed_scope else None,
        })
    new_total = sum(row["allocated"] for row in comparisons)
    legacy_total = sum(row["legacy_reserved"] for row in comparisons)
    differences = [row for row in comparisons if not row["quantity_match"]]
    unaccepted = [row for row in differences if not row["difference_accepted"]]
    status = (
        "insufficient" if not comparisons else
        "match" if not differences else
        "explained_difference" if not unaccepted else
        "diverged"
    )
    quantity_parity_ready = status in {"match", "explained_difference"}
    # The legacy table cannot certify the two dimensions the replacement is
    # designed to protect. An accepted quantity exception is evidence, not a
    # waiver of tenant/location isolation.
    scope_parity_ready = not any(
        limitation in limitations
        for limitation in {
            "legacy_reservations_not_tenant_scoped",
            "legacy_reservations_not_location_scoped",
            "legacy_reservation_table_unavailable",
        }
    )
    report = {"tenant_id": tenant_id, "case_id": case_id, "status": status,
              "new_allocated_qty": new_total, "legacy_reserved_qty": legacy_total,
              "comparisons": comparisons, "limitations": limitations,
              "accepted_difference_codes": sorted(accepted),
              "difference_count": len(differences),
              "unaccepted_difference_count": len(unaccepted),
              "quantity_parity_ready": quantity_parity_ready,
              "scope_parity_ready": scope_parity_ready,
              "replacement_ready": quantity_parity_ready and scope_parity_ready,
              "execution_authority": "legacy_inventory_reservations",
              "parity_exception_verification": parity_exception_verification or {
                  "accepted": [], "rejected": [], "status": "not_evaluated"
              }}
    if persist:
        run_id = str(uuid.uuid4())
        db.execute(text(
            "INSERT INTO allocation_shadow_parity_run "
            "(id,tenant_id,case_id,status,new_allocated_qty,legacy_reserved_qty,details_json,created_at) "
            "VALUES (:id,:t,:case_id,:status,:new,:legacy,:details,:now)"
        ), {"id": run_id, "t": tenant_id, "case_id": case_id, "status": status,
            "new": new_total, "legacy": legacy_total,
            "details": json.dumps(report, sort_keys=True), "now": _now()})
        report["run_id"] = run_id
    return report


def allocation_shadow_parity_from_register(
    db,
    *,
    tenant_id: str,
    case_id: str,
    key_resolver,
    persist: bool = True,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Apply only verified exact-case exceptions while legacy execution remains authoritative."""
    from src.app.services.allocation_parity_exceptions import verified_exception_scopes

    verification = verified_exception_scopes(
        db, tenant_id=tenant_id, case_id=case_id, key_resolver=key_resolver,
        allowed_codes=PARITY_DIFFERENCE_CODES, as_of=as_of,
    )
    verification["status"] = "verified" if not verification["rejected"] else "degraded"
    return allocation_shadow_parity(
        db, tenant_id=tenant_id, case_id=case_id, persist=persist,
        verified_difference_scopes=verification["accepted"],
        parity_exception_verification=verification,
    )


def apply_supplier_schedule(db, *, tenant_id: str, demand_id: str, supplier_id: str,
                            evidence_id: str, schedule_lines: Iterable[dict[str, Any]],
                            observed_at: str, expires_at: str | None = None) -> dict[str, Any]:
    """Persist a bounded supplier observation and recompute the exact buyer promise it supports."""
    from src.app.services.fulfillment.route_policy import normalize_supplier_schedule

    demand = db.execute(text(
        "SELECT quantity,sku,stage FROM demand_commitment WHERE id=:id AND tenant_id=:t"
    ), {"id": demand_id, "t": tenant_id}).fetchone()
    if demand is None:
        raise KeyError("demand_not_found")
    if str(demand[2]) != "committed":
        return {"status": "blocked", "state_prevented": "demand_not_committed"}
    internal = int(db.execute(text(
        "SELECT COALESCE(SUM(quantity),0) FROM demand_allocation "
        "WHERE tenant_id=:t AND demand_id=:id AND status='allocated'"
    ), {"t": tenant_id, "id": demand_id}).scalar() or 0)
    fresh = True
    if expires_at:
        fresh = _parse_timestamp(expires_at) > datetime.now(timezone.utc)
    normalized_lines = [dict(line) for line in schedule_lines]
    outcome = normalize_supplier_schedule(
        requested_qty=int(demand[0]), internal_allocated_qty=internal,
        schedule_lines=normalized_lines, evidence_fresh=fresh,
    )
    for index, line in enumerate(normalized_lines):
        state = str(line.get("status") or "").lower()
        if state not in {"confirmed", "partial", "backordered", "rejected"}:
            continue
        quantity = max(0, int(line.get("quantity") or 0))
        line_evidence = f"{evidence_id}:{index}"
        exists = db.execute(text(
            "SELECT 1 FROM supplier_schedule_allocation WHERE tenant_id=:t "
            "AND demand_id=:d AND evidence_id=:e"
        ), {"t": tenant_id, "d": demand_id, "e": line_evidence}).fetchone()
        if not exists:
            db.execute(text(
                "INSERT INTO supplier_schedule_allocation "
                "(id,tenant_id,demand_id,supplier_id,evidence_id,status,quantity,eta,observed_at,"
                "expires_at,created_at) VALUES (:id,:t,:d,:supplier,:e,:status,:qty,:eta,:observed,"
                ":expires,:now)"
            ), {"id": str(uuid.uuid4()), "t": tenant_id, "d": demand_id,
                "supplier": supplier_id, "e": line_evidence, "status": state, "qty": quantity,
                "eta": line.get("eta"), "observed": observed_at, "expires": expires_at, "now": _now()})
    promise_version = hashlib.sha256(json.dumps(
        {"demand_id": demand_id, "evidence_id": evidence_id, "outcome": outcome},
        sort_keys=True,
    ).encode()).hexdigest()
    from src.app.services.temporal_invalidation import (
        invalidate_derived_dependencies,
        register_derived_dependency,
    )

    invalidate_derived_dependencies(
        db, tenant_id=tenant_id, derived_type="buyer_supply_promise", derived_id=demand_id,
        reason=f"superseded_by_supplier_schedule:{evidence_id}",
    )
    updated = db.execute(text(
        "UPDATE buyer_supply_promise SET promise_version=:version,promise_state=:state,"
        "covered_quantity=:covered,shortfall_quantity=:shortfall,buyer_message=:message,"
        "alternatives_required=:alternatives,updated_at=:now WHERE tenant_id=:t AND demand_id=:d"
    ), {"version": promise_version, "state": outcome["promise_state"],
        "covered": outcome["covered_qty"], "shortfall": outcome["shortfall_qty"],
        "message": outcome["buyer_message"], "alternatives": bool(outcome["alternatives_required"]),
        "now": _now(), "t": tenant_id, "d": demand_id})
    if not getattr(updated, "rowcount", 0):
        db.execute(text(
            "INSERT INTO buyer_supply_promise "
            "(tenant_id,demand_id,promise_version,promise_state,covered_quantity,shortfall_quantity,"
            "buyer_message,alternatives_required,updated_at) VALUES "
            "(:t,:d,:version,:state,:covered,:shortfall,:message,:alternatives,:now)"
        ), {"t": tenant_id, "d": demand_id, "version": promise_version,
            "state": outcome["promise_state"], "covered": outcome["covered_qty"],
            "shortfall": outcome["shortfall_qty"], "message": outcome["buyer_message"],
            "alternatives": bool(outcome["alternatives_required"]), "now": _now()})
    register_derived_dependency(
        db, tenant_id=tenant_id, source_type="supplier_schedule", source_id=evidence_id,
        source_version=observed_at, derived_type="buyer_supply_promise", derived_id=demand_id,
    )
    return {"status": "applied", "demand_id": demand_id, "sku": str(demand[1]),
            "promise_version": promise_version, **outcome}


def apply_supplier_schedule_to_batch(
    db,
    *,
    tenant_id: str,
    batch_id: str,
    supplier_id: str,
    evidence_id: str,
    schedule_lines: Iterable[dict[str, Any]],
    observed_at: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Distribute one aggregate supplier response across child demand deterministically.

    The supplier cannot choose buyers.  Confirmed quantity follows the same sealed priority and age
    ordering as internal ATP.  Every child receives its own promise version and evidence binding.
    """
    batch = db.execute(text(
        "SELECT supplier_id,status,quantity,sku FROM sourcing_batch WHERE id=:id AND tenant_id=:t"
    ), {"id": batch_id, "t": tenant_id}).fetchone()
    if batch is None:
        raise KeyError("sourcing_batch_not_found")
    if str(batch[0] or "") != str(supplier_id):
        return {"status": "blocked", "state_prevented": "supplier_batch_mismatch"}
    rows = db.execute(text(
        "SELECT d.id,c.quantity,d.priority_tier,d.created_at FROM sourcing_batch_demand c "
        "JOIN demand_commitment d ON d.id=c.demand_id WHERE c.batch_id=:batch "
        "AND d.tenant_id=:t AND d.stage='committed' "
        "ORDER BY d.priority_tier,d.created_at,d.id"
    ), {"batch": batch_id, "t": tenant_id}).fetchall()
    if not rows:
        return {"status": "blocked", "state_prevented": "no_committed_child_demand"}
    lines = [dict(line) for line in schedule_lines]
    confirmed_pool = sum(
        max(0, int(line.get("quantity") or 0))
        for line in lines if str(line.get("status") or "").lower() in {"confirmed", "partial"}
    )
    rejected_pool = sum(
        max(0, int(line.get("quantity") or 0))
        for line in lines if str(line.get("status") or "").lower() == "rejected"
    )
    backordered_pool = sum(
        max(0, int(line.get("quantity") or 0))
        for line in lines if str(line.get("status") or "").lower() == "backordered"
    )
    eta_values = sorted({str(line["eta"]) for line in lines if line.get("eta")})
    results: list[dict[str, Any]] = []
    for demand_id, child_quantity, _tier, _created in rows:
        child = int(child_quantity)
        confirmed = min(child, confirmed_pool)
        confirmed_pool -= confirmed
        unresolved = child - confirmed
        rejected = min(unresolved, rejected_pool)
        rejected_pool -= rejected
        unresolved -= rejected
        backordered = min(unresolved, backordered_pool)
        backordered_pool -= backordered
        child_lines: list[dict[str, Any]] = []
        if confirmed:
            child_lines.append({"status": "partial" if confirmed < child else "confirmed",
                                "quantity": confirmed,
                                "eta": eta_values[0] if eta_values else None})
        if rejected:
            child_lines.append({"status": "rejected", "quantity": rejected})
        if backordered:
            child_lines.append({"status": "backordered", "quantity": backordered})
        if unresolved - backordered > 0:
            child_lines.append({"status": "rejected", "quantity": unresolved - backordered})
        outcome = apply_supplier_schedule(
            db, tenant_id=tenant_id, demand_id=str(demand_id), supplier_id=supplier_id,
            evidence_id=f"{evidence_id}:{demand_id}", schedule_lines=child_lines,
            observed_at=observed_at, expires_at=expires_at,
        )
        results.append(outcome)
    confirmed_total = sum(int(row.get("supplier_confirmed_qty") or 0) for row in results)
    unresolved_total = sum(int(row.get("shortfall_qty") or 0) for row in results)
    from src.app.services.supply_recovery import project_supply_recovery
    recovery = project_supply_recovery(
        db, tenant_id=tenant_id, sku=str(batch[3]), excluded_supplier_id=supplier_id,
    ) if unresolved_total > 0 else {
        "status": "not_required", "alternative_suppliers": [],
        "qualified_substitutes": [], "external_action": "none",
    }
    return {"status": "applied", "batch_id": batch_id, "supplier_id": supplier_id,
            "confirmed_quantity": confirmed_total, "unresolved_quantity": unresolved_total,
            "alternatives_required": unresolved_total > 0, "demands": results,
            "recovery": recovery,
            "allocation_policy": "priority_then_age_then_stable_id",
            "external_action": "none"}


def allocation_workbench(db, *, tenant_id: str, sku: str | None = None,
                         limit: int = 100) -> dict[str, Any]:
    """Buyer-safe portfolio projection; identities are represented only by stable anonymous labels."""
    sku_clause = " AND d.sku=:sku" if sku else ""
    params: dict[str, Any] = {"t": tenant_id, "limit": max(1, min(int(limit), 500))}
    if sku:
        params["sku"] = sku
    rows = db.execute(text(
        "SELECT d.id,d.case_id,d.sku,d.uom,d.destination_id,d.stage,d.quantity,d.priority_tier,"
        "d.required_by,d.created_at,COALESCE(SUM(CASE WHEN a.status='allocated' THEN a.quantity ELSE 0 END),0),"
        "p.promise_state,p.covered_quantity,p.shortfall_quantity,p.alternatives_required,"
        "d.fulfillment_location_id "
        "FROM demand_commitment d LEFT JOIN demand_allocation a ON a.demand_id=d.id "
        "LEFT JOIN buyer_supply_promise p ON p.tenant_id=d.tenant_id AND p.demand_id=d.id "
        "WHERE d.tenant_id=:t" + sku_clause +
        " GROUP BY d.id,d.case_id,d.sku,d.uom,d.destination_id,d.stage,d.quantity,d.priority_tier,"
        "d.required_by,d.created_at,p.promise_state,p.covered_quantity,p.shortfall_quantity,"
        "p.alternatives_required,d.fulfillment_location_id "
        "ORDER BY d.priority_tier,d.created_at,d.id LIMIT :limit"
    ), params).fetchall()
    now = datetime.now(timezone.utc)
    demands = []
    for row in rows:
        age = max(0, int((now - _parse_timestamp(str(row[9]))).total_seconds()))
        demands.append({"demand_ref": "Demand " + hashlib.sha256(str(row[0]).encode()).hexdigest()[:8],
                        "case_ref": "Case " + hashlib.sha256(str(row[1] or row[0]).encode()).hexdigest()[:8],
                        "sku": str(row[2]), "uom": str(row[3]), "destination_id": str(row[4]),
                        "stage": str(row[5]), "requested_quantity": int(row[6]),
                        "priority_tier": int(row[7]), "required_by": row[8], "queue_age_seconds": age,
                        "allocated_quantity": int(row[10] or 0), "promise_state": row[11],
                        "covered_quantity": int(row[12] or 0) if row[12] is not None else int(row[10] or 0),
                        "shortfall_quantity": int(row[13] or 0) if row[13] is not None
                        else max(0, int(row[6]) - int(row[10] or 0)),
                        "alternatives_required": bool(row[14]),
                        "fulfillment_location_id": row[15],
                        "allocation_state_prevented": (
                            None if row[15] else "fulfillment_location_unresolved"
                        )})
    batches = db.execute(text(
        "SELECT b.id,b.sku,b.destination_id,b.status,b.quantity,b.window_ends_at,"
        "COUNT(c.demand_id),b.fulfillment_case_id,b.draft_content_hash,b.supplier_id "
        "FROM sourcing_batch b LEFT JOIN sourcing_batch_demand c ON c.batch_id=b.id "
        "WHERE b.tenant_id=:t" + (" AND b.sku=:sku" if sku else "") +
        " GROUP BY b.id,b.sku,b.destination_id,b.status,b.quantity,b.window_ends_at,"
        "b.fulfillment_case_id,b.draft_content_hash,b.supplier_id ORDER BY b.created_at DESC LIMIT :limit"
    ), params).fetchall()
    waves = db.execute(text(
        "SELECT w.id,w.supplier_id,w.supplier_facility_id,w.currency,w.incoterm,"
        "w.merchant_destination_id,w.status,w.window_ends_at,w.standalone_freight_cents,"
        "w.consolidated_freight_cents,w.handling_cents,w.estimated_savings_cents,"
        "COUNT(wb.batch_id),COALESCE(SUM(b.quantity),0) FROM sourcing_wave w "
        "LEFT JOIN sourcing_wave_batch wb ON wb.wave_id=w.id "
        "LEFT JOIN sourcing_batch b ON b.id=wb.batch_id WHERE w.tenant_id=:t "
        + ("AND EXISTS (SELECT 1 FROM sourcing_wave_batch swb "
           "JOIN sourcing_batch sb ON sb.id=swb.batch_id "
           "WHERE swb.wave_id=w.id AND sb.tenant_id=:t AND sb.sku=:sku) " if sku else "") +
        "GROUP BY w.id,w.supplier_id,w.supplier_facility_id,w.currency,w.incoterm,"
        "w.merchant_destination_id,w.status,w.window_ends_at,w.standalone_freight_cents,"
        "w.consolidated_freight_cents,w.handling_cents,w.estimated_savings_cents "
        "ORDER BY w.created_at DESC LIMIT :limit"
    ), params).fetchall()
    routes = db.execute(text(
        "SELECT r.id,r.case_id,r.mode,r.status,r.destination_token,r.eta_min_days,r.eta_max_days,"
        "r.components_json,r.state_prevented,r.pii_release_authorized,r.created_at,"
        "a.status,a.jurisdiction,a.purpose,a.retention_until "
        "FROM fulfillment_route_proposal r LEFT JOIN direct_ship_authorization a "
        "ON a.tenant_id=r.tenant_id AND a.case_id=r.case_id AND a.destination_token=r.destination_token "
        "WHERE r.tenant_id=:t ORDER BY r.created_at DESC LIMIT :limit"
    ), params).fetchall()
    promise_calculations: list[dict[str, Any]] = []
    workbench_tables = set(inspect(db.connection()).get_table_names())
    if "promise_calculation" in workbench_tables:
        for case_id in sorted({str(row[1]) for row in rows if row[1]}):
            promise_row = db.execute(text(
                "SELECT option_id,calculation_version,requested_quantity,requested_arrival_at,"
                "feasibility,confirmed_quantity,unknown_quantity,quantity_by_deadline,"
                "latest_viable_response_at,earliest_arrival_at,latest_arrival_at,carrier_cutoff_at,"
                "dispatch_ready_at,evaluated_at,response_expectation_json,reason_codes_json,"
                "dependencies_json,calculated_at FROM promise_calculation "
                "WHERE tenant_id=:tenant AND case_id=:case_id AND status='active' "
                "ORDER BY calculated_at DESC LIMIT 1"
            ), {"tenant": tenant_id, "case_id": case_id}).fetchone()
            if promise_row is None:
                continue
            promise_calculations.append({
                "case_ref": "Case " + hashlib.sha256(case_id.encode()).hexdigest()[:8],
                "option_id": str(promise_row[0]), "calculation_version": str(promise_row[1]),
                "requested_quantity": int(promise_row[2]), "requested_arrival_at": str(promise_row[3]),
                "feasibility": str(promise_row[4]), "quantity_confirmed_by_deadline": int(promise_row[5]),
                "unknown_quantity": int(promise_row[6]), "quantity_by_deadline": int(promise_row[7]),
                "remaining_quantity": max(0, int(promise_row[2]) - int(promise_row[7])),
                "latest_viable_supplier_response_at": promise_row[8],
                "earliest_arrival_range": {"earliest": promise_row[9], "latest": promise_row[10]},
                "carrier_cutoff_at": promise_row[11], "dispatch_ready_at": promise_row[12],
                "evaluated_at": str(promise_row[13]),
                "response_expectation": json.loads(str(promise_row[14] or "{}")),
                "failed_constraints": json.loads(str(promise_row[15] or "[]")),
                "dependency_versions": json.loads(str(promise_row[16] or "{}")),
                "calculated_at": str(promise_row[17]),
                "state_prevented": (
                    None if str(promise_row[4]) == "met" else "unsupported_full_delivery_promise"
                ),
            })
    case_ids = sorted({str(row[1]) for row in rows if row[1]})
    outbound_contact_schedule = None
    human_room = None
    canonical_escalation = None
    payment_consequence = None
    if case_ids and "outbound_message" in workbench_tables:
        params_cases = {f"case_{index}": value for index, value in enumerate(case_ids)}
        clause = ",".join(f":case_{index}" for index in range(len(case_ids)))
        outbound = db.execute(text(
            "SELECT channel,status,next_attempt_at,schedule_reason,sla_clock,transport_eligible "
            "FROM outbound_message WHERE tenant_id=:tenant AND case_id IN (" + clause + ") "
            "ORDER BY created_at DESC LIMIT 1"
        ), {"tenant": tenant_id, **params_cases}).first()
        if outbound:
            outbound_contact_schedule = {
                "channel": str(outbound[0]), "queue_state": str(outbound[1]),
                "not_before": outbound[2], "schedule_reason": outbound[3],
                "sla_clock": str(outbound[4] or "unknown"),
                "transport_eligible": bool(outbound[5]),
            }
    if case_ids and "procurement_human_room" in workbench_tables:
        params_cases = {f"case_{index}": value for index, value in enumerate(case_ids)}
        clause = ",".join(f":case_{index}" for index in range(len(case_ids)))
        room = db.execute(text(
            "SELECT state,assigned_operator_id,version,updated_at FROM procurement_human_room "
            "WHERE tenant_id=:tenant AND case_id IN (" + clause + ") ORDER BY updated_at DESC LIMIT 1"
        ), {"tenant": tenant_id, **params_cases}).first()
        if room:
            human_room = {"state": str(room[0]), "assigned_operator_id": room[1],
                          "version": int(room[2]), "updated_at": str(room[3])}
    if case_ids and "case_escalation" in workbench_tables:
        params_cases = {f"case_{index}": value for index, value in enumerate(case_ids)}
        clause = ",".join(f":case_{index}" for index in range(len(case_ids)))
        escalation_row = db.execute(text(
            "SELECT id FROM case_escalation WHERE tenant_id=:tenant "
            "AND case_id IN (" + clause + ") AND state!='resolved' "
            "ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END, created_at LIMIT 1"
        ), {"tenant": tenant_id, **params_cases}).first()
        if escalation_row:
            from src.app.services.case_escalation import get_escalation
            from src.app.services.case_escalation_projection import list_escalation_projections

            canonical_escalation = get_escalation(
                db, tenant_id=tenant_id, escalation_id=str(escalation_row[0])
            )
            canonical_escalation["projections"] = list_escalation_projections(
                db, tenant_id=tenant_id, escalation_id=str(escalation_row[0])
            ) if "case_escalation_projection" in workbench_tables else []
    if case_ids and "procurement_payment_consequence" in workbench_tables:
        params_cases = {f"case_{index}": value for index, value in enumerate(case_ids)}
        clause = ",".join(f":case_{index}" for index in range(len(case_ids)))
        payment = db.execute(text(
            "SELECT consequence_json FROM procurement_payment_consequence "
            "WHERE tenant_id=:tenant AND case_id IN (" + clause + ") AND superseded_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1"
        ), {"tenant": tenant_id, **params_cases}).first()
        if payment:
            payment_consequence = json.loads(str(payment[0] or "{}"))
    committed = [row for row in demands if row["stage"] == "committed"]
    total_requested = sum(row["requested_quantity"] for row in committed)
    total_allocated = sum(row["allocated_quantity"] for row in committed)
    supplier_confirmed = sum(
        max(0, int(row["covered_quantity"]) - int(row["allocated_quantity"]))
        for row in committed
        if row["promise_state"]
    )
    supplier_unresolved = sum(
        int(row["shortfall_quantity"])
        for row in committed
        if row["promise_state"]
    )
    supplier_refs = [(str(row[1]), str(row[2])) for row in waves]
    from src.app.services.supply_recovery import project_supply_recovery
    recovery_options = []
    for batch_row in batches:
        needs_recovery = db.execute(text(
            "SELECT COUNT(*) FROM sourcing_batch_demand c "
            "JOIN buyer_supply_promise p ON p.tenant_id=:t AND p.demand_id=c.demand_id "
            "WHERE c.batch_id=:batch AND p.alternatives_required IS TRUE"
        ), {"t": tenant_id, "batch": str(batch_row[0])}).scalar()
        if not int(needs_recovery or 0):
            continue
        recovery_options.append({
            "batch_ref": "Batch " + str(batch_row[0])[:8],
            "sku": str(batch_row[1]),
            "unresolved_child_count": int(needs_recovery),
            **project_supply_recovery(
                db, tenant_id=tenant_id, sku=str(batch_row[1]),
                excluded_supplier_id=str(batch_row[9] or ""),
            ),
        })
    from src.app.services.disruption_intelligence import disruption_workbench_projection
    from src.app.services.temporal_invalidation import tenant_cache_lifecycle_projection
    return {"tenant_id": tenant_id, "sku": sku, "authority": "shadow_allocation",
            "execution_authority": "legacy_inventory_reservations",
            "summary": {"committed_quantity": total_requested, "allocated_quantity": total_allocated,
                        "shortfall_quantity": max(0, total_requested - total_allocated),
                        "supplier_confirmed_quantity": supplier_confirmed,
                        "supplier_unresolved_quantity": supplier_unresolved,
                        "allocation_pressure": (
                            round(max(0, total_requested - total_allocated) / total_requested, 4)
                            if total_requested else 0.0),
                        "oldest_queue_age_seconds": max((row["queue_age_seconds"] for row in committed), default=0)},
            "demands": demands,
            "promise_calculations": promise_calculations,
            "promise_calculation": promise_calculations[0] if promise_calculations else None,
            "outbound_contact_schedule": outbound_contact_schedule,
            "human_room": human_room,
            "canonical_escalation": canonical_escalation,
            "payment_consequence": payment_consequence,
            "sourcing_batches": [
                {"batch_ref": "Batch " + str(row[0])[:8], "sku": str(row[1]),
                 "destination_id": str(row[2]), "status": str(row[3]), "quantity": int(row[4]),
                 "window_ends_at": str(row[5]), "child_demand_count": int(row[6]),
                 "fulfillment_case_id": row[7], "draft_content_hash": row[8]}
                for row in batches
            ],
            "sourcing_waves": [
                {"wave_ref": "Wave " + str(row[0])[:8], "supplier_id": str(row[1]),
                 "supplier_facility_id": str(row[2]), "currency": str(row[3]),
                 "incoterm": str(row[4]), "merchant_destination_id": str(row[5]),
                 "status": str(row[6]), "window_ends_at": str(row[7]),
                 "standalone_freight_cents": int(row[8]),
                 "consolidated_freight_cents": int(row[9]), "handling_cents": int(row[10]),
                 "estimated_savings_cents": int(row[11]), "batch_count": int(row[12]),
                 "total_quantity": int(row[13])}
                for row in waves
            ],
            "route_proposals": [
                {"proposal_ref": "Route " + str(row[0])[:8], "case_ref": "Case " +
                 hashlib.sha256(str(row[1]).encode()).hexdigest()[:8], "mode": str(row[2]),
                 "status": str(row[3]), "destination_token": str(row[4]),
                 "eta_days": {"min": row[5], "max": row[6]},
                 "components": json.loads(str(row[7] or "{}")), "state_prevented": row[8],
                 "pii_release_authorized": bool(row[9]), "created_at": str(row[10]),
                 "privacy": {"status": row[11] or "not_required", "jurisdiction": row[12],
                             "purpose": row[13], "retention_until": row[14]}}
                for row in routes
            ],
             "supplier_pressure": supplier_pressure_projection(
                 db, tenant_id=tenant_id, supplier_refs=supplier_refs,
             ),
            "recovery_options": recovery_options,
            "disruption_impacts": disruption_workbench_projection(
                db, tenant_id=tenant_id, sku=sku, limit=min(limit, 25),
            ),
            "temporal_cache_lifecycle": tenant_cache_lifecycle_projection(
                db, tenant_id=tenant_id, limit=min(limit, 20),
            ),
             "privacy": {"buyer_identities_exposed": False, "child_demands_anonymized": True}}


def buyer_procurement_context(db, *, tenant_id: str, case_id: str,
                              buyer_ref_hash: str) -> dict[str, Any]:
    """Return only one authenticated buyer's ledger projection; portfolio identities never leak."""
    rows = db.execute(text(
        "SELECT d.id,d.sku,d.uom,d.destination_id,d.stage,d.quantity,d.required_by,d.updated_at,"
        "COALESCE(SUM(CASE WHEN a.status='allocated' THEN a.quantity ELSE 0 END),0),"
        "p.promise_state,p.covered_quantity,p.shortfall_quantity,p.buyer_message,p.alternatives_required,"
        "d.fulfillment_location_id "
        "FROM demand_commitment d LEFT JOIN demand_allocation a ON a.demand_id=d.id "
        "LEFT JOIN buyer_supply_promise p ON p.tenant_id=d.tenant_id AND p.demand_id=d.id "
        "WHERE d.tenant_id=:t AND d.case_id=:case AND d.buyer_ref_hash=:buyer "
        "GROUP BY d.id,d.sku,d.uom,d.destination_id,d.stage,d.quantity,d.required_by,d.updated_at,"
        "p.promise_state,p.covered_quantity,p.shortfall_quantity,p.buyer_message,p.alternatives_required,"
        "d.fulfillment_location_id "
        "ORDER BY d.updated_at DESC"
    ), {"t": tenant_id, "case": case_id, "buyer": buyer_ref_hash}).fetchall()
    if not rows:
        return {"status": "not_found", "case_id": case_id, "lines": []}
    lines = []
    for row in rows:
        allocated = int(row[8] or 0)
        requested = int(row[5])
        pool = db.execute(text(
            "SELECT snapshot_version,observed_at,expires_at,source_authority,completeness "
            "FROM supply_allocation_pool WHERE tenant_id=:t AND sku=:sku AND uom=:uom "
            "AND location_id=:loc"
        ), {"t": tenant_id, "sku": row[1], "uom": row[2], "loc": row[14]}).fetchone() if row[14] else None
        freshness = "unknown"
        if pool:
            freshness = "stale" if pool[2] and _parse_timestamp(str(pool[2])) <= datetime.now(timezone.utc) else "current"
        lines.append({"demand_ref": hashlib.sha256(str(row[0]).encode()).hexdigest()[:12],
                      "sku": str(row[1]), "uom": str(row[2]), "destination_token": str(row[3]),
                      "stage": str(row[4]), "requested_quantity": requested,
                      "required_by": row[6], "updated_at": str(row[7]),
                      "allocated_quantity": allocated,
                      "promise_state": row[9] or ("partial" if allocated else "unconfirmed"),
                      "covered_quantity": int(row[10] or allocated),
                      "shortfall_quantity": int(row[11]) if row[11] is not None else max(0, requested - allocated),
                      "buyer_message": row[12], "alternatives_required": bool(row[13]),
                      "fulfillment_location_id": row[14],
                      "allocation_state_prevented": (
                          None if row[14] else "fulfillment_location_unresolved"
                      ),
                      "atp_evidence": ({"snapshot_version": str(pool[0]), "observed_at": str(pool[1]),
                                        "freshness": freshness, "authority": str(pool[3]),
                                        "completeness": str(pool[4])} if pool else None)})
    return {"status": "available", "case_id": case_id, "authority": "buyer_scoped_ledger",
            "lines": lines, "privacy": {"other_buyers_visible": False}}


def materialize_governed_rfq_for_batch(db, *, tenant_id: str, batch_id: str,
                                       trace_id: str | None = None) -> dict[str, Any]:
    """Create one human-gated fulfillment case and RFQ draft for a committed sourcing batch.

    Child demand remains the allocation authority. This projection cannot include provisional demand or
    speculative buffer, and it never approves or sends the resulting message.
    """
    batch_row = db.execute(text(
        "SELECT id,sku,uom,destination_id,supplier_id,status,quantity,speculative_quantity,"
        "fulfillment_case_id,draft_content_hash FROM sourcing_batch "
        "WHERE id=:id AND tenant_id=:t"
    ), {"id": batch_id, "t": tenant_id}).fetchone()
    if batch_row is None:
        raise KeyError("sourcing_batch_not_found")
    if int(batch_row[7] or 0) > 0:
        return {"status": "blocked", "state_prevented": "speculative_inventory_requires_separate_approval"}
    children = db.execute(text(
        "SELECT d.id,d.case_id,d.stage,d.sku,c.quantity,d.required_by "
        "FROM sourcing_batch_demand c JOIN demand_commitment d ON d.id=c.demand_id "
        "WHERE c.batch_id=:batch ORDER BY d.id"
    ), {"batch": batch_id}).fetchall()
    if not children or any(str(row[2]) != "committed" for row in children):
        return {"status": "blocked", "state_prevented": "uncommitted_child_demand"}
    if batch_row[8]:
        return {"status": "drafted", "fulfillment_case_id": str(batch_row[8]),
                "content_hash": str(batch_row[9] or ""), "idempotent": True,
                "external_action": "none"}

    from src.app.services.fulfillment import draft as supplier_draft
    from src.app.services.fulfillment import workflow
    from src.app.services.fulfillment.domain import Actor, ActorType

    quantity = int(batch_row[6])
    sku = str(batch_row[1])
    required_values = sorted(str(row[5]) for row in children if row[5])
    requirements = {"destination_token": str(batch_row[3])}
    if required_values:
        requirements["required_by"] = required_values[0]
    state_json = {
        "sourcing_batch_id": batch_id,
        "requirements": requirements,
        "availability": {"requested_qty": quantity, "in_stock": 0, "shortfall": quantity,
                         "item_ref": sku},
        "order_lines": [{"item_ref": sku, "quantity": quantity}],
        "child_demand_count": len(children),
        "child_demand_refs": [hashlib.sha256(str(row[0]).encode()).hexdigest()[:12] for row in children],
    }
    case_id = workflow.open_case(
        db, buyer_uid_hash="consolidated:" + hashlib.sha256(batch_id.encode()).hexdigest()[:16],
        source_trace_id=trace_id, requested_by="Demand_Consolidation_Agent",
        tenant_id=tenant_id, state_json=state_json,
    )
    if not case_id:
        return {"status": "degraded", "reason": "case_create_failed"}
    agent = Actor(ActorType.AGENT, "Demand_Consolidation_Agent")
    buyer = Actor(ActorType.BUYER, "committed_child_demands")
    transitions = [
        workflow.transition(
            db, case_id=case_id, event="availability_assessed", actor=agent,
            reason_code="consolidated_committed_shortfall", state_patch=state_json,
            evidence={"batch_id": batch_id, "child_demand_count": len(children)},
            tenant_id=tenant_id, trace_id=trace_id,
        ),
        workflow.transition(
            db, case_id=case_id, event="request_buyer_commitment", actor=agent,
            reason_code="commitment_already_captured_per_child", tenant_id=tenant_id,
            trace_id=trace_id,
        ),
        workflow.transition(
            db, case_id=case_id, event="buyer_committed", actor=buyer,
            reason_code="committed_child_demand_ledger", tenant_id=tenant_id,
            trace_id=trace_id,
        ),
    ]
    if not all(item.ok for item in transitions):
        return {"status": "degraded", "reason": "case_transition_failed",
                "transition_reasons": [item.reason for item in transitions]}
    draft_result, draft = supplier_draft.draft_and_record(
        db, case_id=case_id, actor=agent, item_ref=sku, quantity=quantity,
        tenant_id=tenant_id, trace_id=trace_id,
        needed_by=(requirements.get("required_by") or "the stated deadline"),
        lines=[{"item_ref": sku, "quantity": quantity}],
    )
    if not draft_result.ok or draft is None:
        return {"status": "degraded", "fulfillment_case_id": case_id,
                "reason": draft_result.reason, "external_action": "none"}
    db.execute(text(
        "UPDATE sourcing_batch SET status='rfq_drafted',fulfillment_case_id=:case,"
        "draft_content_hash=:hash,updated_at=:now WHERE id=:id AND tenant_id=:t"
    ), {"case": case_id, "hash": draft.content_hash, "now": _now(),
        "id": batch_id, "t": tenant_id})
    return {"status": "drafted", "fulfillment_case_id": case_id,
            "content_hash": draft.content_hash, "child_demand_count": len(children),
            "human_approval_required": True, "external_action": "none", "idempotent": False}


def materialize_governed_rfq_for_wave(
    db, *, tenant_id: str, wave_id: str, trace_id: str | None = None,
) -> dict[str, Any]:
    """Create one supplier-bound, multi-line RFQ draft for a compatible shipment wave.

    The wave and every child batch/demand remain addressable.  The function drafts only; it
    cannot approve, queue, send, create a PO, or authorize payment.
    """
    wave = db.execute(text(
        "SELECT id,supplier_id,supplier_facility_id,merchant_destination_id,status,"
        "fulfillment_case_id,draft_content_hash,parent_rfq_ref FROM sourcing_wave "
        "WHERE id=:id AND tenant_id=:t"
    ), {"id": wave_id, "t": tenant_id}).fetchone()
    if wave is None:
        raise KeyError("sourcing_wave_not_found")
    if wave[5]:
        return {
            "status": "drafted", "fulfillment_case_id": str(wave[5]),
            "content_hash": str(wave[6] or ""), "parent_rfq_ref": str(wave[7] or ""),
            "idempotent": True, "external_action": "none",
        }
    batches = db.execute(text(
        "SELECT b.id,b.sku,b.uom,b.destination_id,b.supplier_id,b.status,b.quantity,"
        "b.speculative_quantity,b.fulfillment_case_id FROM sourcing_wave_batch wb "
        "JOIN sourcing_batch b ON b.id=wb.batch_id "
        "WHERE wb.wave_id=:wave AND b.tenant_id=:t ORDER BY b.sku,b.id"
    ), {"wave": wave_id, "t": tenant_id}).fetchall()
    if not batches:
        return {"status": "blocked", "state_prevented": "empty_sourcing_wave"}
    if any(int(row[7] or 0) > 0 for row in batches):
        return {"status": "blocked", "state_prevented": "speculative_inventory_requires_separate_approval"}
    if any(row[8] or str(row[5]) != "draft" for row in batches):
        return {"status": "blocked", "state_prevented": "child_batch_already_materialized"}
    if any(str(row[4]) != str(wave[1]) or str(row[3]) != str(wave[3]) for row in batches):
        return {"status": "blocked", "state_prevented": "incompatible_child_batch"}

    child_rows = db.execute(text(
        "SELECT wb.batch_id,d.id,d.case_id,d.stage,d.required_by,d.updated_at FROM sourcing_wave_batch wb "
        "JOIN sourcing_batch_demand cbd ON cbd.batch_id=wb.batch_id "
        "JOIN demand_commitment d ON d.id=cbd.demand_id "
        "WHERE wb.wave_id=:wave ORDER BY wb.batch_id,d.id"
    ), {"wave": wave_id}).fetchall()
    if not child_rows or any(str(row[3]) != "committed" for row in child_rows):
        return {"status": "blocked", "state_prevented": "uncommitted_child_demand"}

    supplier = db.execute(text(
        "SELECT s.reliability_score,d.domain FROM suppliers s "
        "JOIN trusted_supplier_domains d ON d.supplier_id=s.id AND d.active=1 "
        "WHERE s.id=:supplier AND s.active=1 ORDER BY d.added_at DESC LIMIT 1"
    ), {"supplier": str(wave[1])}).fetchone()
    if supplier is None or not str(supplier[1] or "").strip():
        return {"status": "blocked", "state_prevented": "supplier_identity_not_approved"}

    from src.app.services.fulfillment import draft as supplier_draft
    from src.app.services.fulfillment import workflow
    from src.app.services.fulfillment.domain import Actor, ActorType

    lines = [{"item_ref": str(row[1]), "quantity": int(row[6])} for row in batches]
    total_quantity = sum(int(line["quantity"]) for line in lines)
    required_values = sorted(str(row[4]) for row in child_rows if row[4])
    temporal_submitted_at = datetime.now(timezone.utc)
    from src.app.services.temporal_authority_repository import (
        record_temporal_expectation,
        supplier_response_expectation,
    )
    response_expectation = supplier_response_expectation(
        db, tenant_id=tenant_id, supplier_id=str(wave[1]),
        supplier_facility_id=str(wave[2]), channel="email",
        submitted_at=temporal_submitted_at,
    )
    parent_rfq_ref = f"RFQ-WAVE-{hashlib.sha256((tenant_id + ':' + wave_id).encode()).hexdigest()[:16]}"
    child_refs = [hashlib.sha256(str(row[1]).encode()).hexdigest()[:12] for row in child_rows]
    state_json = {
        "sourcing_wave_id": wave_id,
        "parent_rfq_ref": parent_rfq_ref,
        "supplier_id": str(wave[1]),
        "supplier_facility_id": str(wave[2]),
        "requirements": {
            "destination_token": str(wave[3]),
            **({"required_by": required_values[0]} if required_values else {}),
        },
        "availability": {"requested_qty": total_quantity, "in_stock": 0,
                         "shortfall": total_quantity, "item_ref": str(lines[0]["item_ref"])},
        "order_lines": lines,
        "child_batch_refs": [str(row[0]) for row in batches],
        "child_demand_count": len(child_rows),
        "child_demand_refs": child_refs,
        "supplier_response_expectation": response_expectation,
    }
    case_id = workflow.open_case(
        db, buyer_uid_hash="wave:" + hashlib.sha256(wave_id.encode()).hexdigest()[:16],
        source_trace_id=trace_id, requested_by="Sourcing_Wave_Agent", tenant_id=tenant_id,
        state_json=state_json,
    )
    if not case_id:
        return {"status": "degraded", "reason": "case_create_failed"}
    agent = Actor(ActorType.AGENT, "Sourcing_Wave_Agent")
    buyer = Actor(ActorType.BUYER, "committed_child_demands")
    transitions = [
        workflow.transition(
            db, case_id=case_id, event="availability_assessed", actor=agent,
            reason_code="supplier_wave_committed_shortfall", state_patch=state_json,
            evidence={"wave_id": wave_id, "batch_count": len(batches),
                      "child_demand_count": len(child_rows)},
            tenant_id=tenant_id, trace_id=trace_id,
        ),
        workflow.transition(
            db, case_id=case_id, event="request_buyer_commitment", actor=agent,
            reason_code="commitment_already_captured_per_child", tenant_id=tenant_id,
            trace_id=trace_id,
        ),
        workflow.transition(
            db, case_id=case_id, event="buyer_committed", actor=buyer,
            reason_code="committed_child_demand_ledger", tenant_id=tenant_id,
            trace_id=trace_id,
        ),
    ]
    if not all(item.ok for item in transitions):
        return {"status": "degraded", "reason": "case_transition_failed",
                "transition_reasons": [item.reason for item in transitions]}
    draft_result, draft = supplier_draft.draft_and_record(
        db, case_id=case_id, actor=agent, item_ref=str(lines[0]["item_ref"]),
        quantity=total_quantity, tenant_id=tenant_id, trace_id=trace_id,
        needed_by=(required_values[0] if required_values else "the stated deadline"),
        lines=lines,
        supplier_override=(str(wave[1]), str(supplier[1]), float(supplier[0] or 0.0),
                           "approved supplier bound to compatible shipment wave"),
    )
    if not draft_result.ok or draft is None:
        return {"status": "degraded", "fulfillment_case_id": case_id,
                "reason": draft_result.reason, "external_action": "none"}
    db.execute(text(
        "UPDATE sourcing_wave SET status='rfq_drafted',fulfillment_case_id=:case,"
        "draft_content_hash=:hash,parent_rfq_ref=:rfq,updated_at=:now "
        "WHERE id=:id AND tenant_id=:t"
    ), {"case": case_id, "hash": draft.content_hash, "rfq": parent_rfq_ref,
        "now": _now(), "id": wave_id, "t": tenant_id})
    db.execute(text(
        "UPDATE sourcing_batch SET status='rfq_drafted',fulfillment_case_id=:case,"
        "draft_content_hash=:hash,updated_at=:now WHERE id IN "
        "(SELECT batch_id FROM sourcing_wave_batch WHERE wave_id=:wave) AND tenant_id=:t"
    ), {"case": case_id, "hash": draft.content_hash, "now": _now(),
        "wave": wave_id, "t": tenant_id})
    from src.app.services.temporal_invalidation import register_derived_dependency

    for child in child_rows:
        register_derived_dependency(
            db, tenant_id=tenant_id, source_type="committed_demand", source_id=str(child[1]),
            source_version=str(child[5] or "unknown"), derived_type="procurement_proposal",
            derived_id=parent_rfq_ref,
        )
    temporal_record = None
    if "temporal_expectation" in set(inspect(db.connection()).get_table_names()):
        temporal_record = record_temporal_expectation(
            db, tenant_id=tenant_id, subject_type="rfq", subject_id=parent_rfq_ref,
            channel="email", submitted_at=temporal_submitted_at,
            expectation=response_expectation,
        )
    return {
        "status": "drafted", "fulfillment_case_id": case_id,
        "parent_rfq_ref": parent_rfq_ref, "content_hash": draft.content_hash,
        "child_batch_count": len(batches), "child_demand_count": len(child_rows),
        "lines": lines, "supplier_id": str(wave[1]),
        "supplier_response_expectation": response_expectation,
        "temporal_expectation_record": temporal_record,
        "human_approval_required": True, "external_action": "none", "idempotent": False,
    }
