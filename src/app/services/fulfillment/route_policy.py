"""Provider-neutral fulfillment routing and supplier schedule recovery contracts."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import text


MODES = frozenset({"supplier_direct", "merchant_inspected", "cross_dock", "split"})
LINE_STATES = frozenset({"confirmed", "partial", "backordered", "rejected"})
DELIVERY_FIELDS = frozenset({
    "recipient_name", "company_name", "street_address", "address_line_2", "locality",
    "region", "postal_code", "country_code", "delivery_phone", "delivery_instructions",
})


def _range(value: tuple[int, int]) -> tuple[int, int]:
    low, high = int(value[0]), int(value[1])
    if low < 0 or high < low:
        raise ValueError("invalid_duration_range")
    return low, high


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def authorize_direct_shipping(
    db, *, tenant_id: str, case_id: str, supplier_id: str, destination_token: str,
    jurisdiction: str, purpose: str, permitted_fields: Iterable[str], retention_until: str,
    authorized_by: str, audit_evidence_id: str,
) -> dict[str, Any]:
    """Persist specific, minimal and withdrawable disclosure authority without storing destination PII."""
    fields = sorted({str(value).strip() for value in permitted_fields if str(value).strip()})
    if not fields or any(value not in DELIVERY_FIELDS for value in fields):
        raise ValueError("invalid_direct_ship_fields")
    if not {"recipient_name", "street_address", "postal_code"}.issubset(fields):
        raise ValueError("minimum_delivery_fields_required")
    expiry = datetime.fromisoformat(str(retention_until).replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        raise ValueError("direct_ship_retention_expired")
    material = {
        "tenant_id": tenant_id, "case_id": case_id, "supplier_id": supplier_id,
        "destination_token": destination_token, "jurisdiction": jurisdiction,
        "purpose": purpose, "permitted_fields": fields, "retention_until": expiry.isoformat(),
        "authorized_by": authorized_by, "audit_evidence_id": audit_evidence_id,
    }
    idem = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    existing = db.execute(text(
        "SELECT id,status,authorized_at,withdrawn_at FROM direct_ship_authorization "
        "WHERE tenant_id=:t AND idempotency_key=:idem"
    ), {"t": tenant_id, "idem": idem}).fetchone()
    if existing:
        return {**material, "authorization_id": str(existing[0]), "status": str(existing[1]),
                "authorized_at": str(existing[2]), "withdrawn_at": existing[3], "idempotent": True}
    authorization_id = str(uuid.uuid4())
    now = _now()
    db.execute(text(
        "INSERT INTO direct_ship_authorization "
        "(id,tenant_id,case_id,supplier_id,destination_token,jurisdiction,purpose,"
        "permitted_fields_json,retention_until,status,authorized_by,authorized_at,"
        "audit_evidence_id,idempotency_key) VALUES "
        "(:id,:t,:case,:supplier,:destination,:jurisdiction,:purpose,:fields,:retention,'active',"
        ":actor,:now,:evidence,:idem)"
    ), {"id": authorization_id, "t": tenant_id, "case": case_id, "supplier": supplier_id,
        "destination": destination_token, "jurisdiction": jurisdiction, "purpose": purpose,
        "fields": json.dumps(fields), "retention": expiry.isoformat(), "actor": authorized_by,
        "now": now, "evidence": audit_evidence_id, "idem": idem})
    return {**material, "authorization_id": authorization_id, "status": "active",
            "authorized_at": now, "withdrawn_at": None, "idempotent": False}


def withdraw_direct_shipping_authorization(
    db, *, tenant_id: str, authorization_id: str, actor_id: str,
) -> dict[str, Any]:
    row = db.execute(text(
        "SELECT case_id,supplier_id,destination_token,jurisdiction,purpose,permitted_fields_json,"
        "retention_until,status,authorized_by,authorized_at,audit_evidence_id "
        "FROM direct_ship_authorization WHERE id=:id AND tenant_id=:t"
    ), {"id": authorization_id, "t": tenant_id}).fetchone()
    if row is None:
        raise KeyError("direct_ship_authorization_not_found")
    withdrawn_at = _now()
    if str(row[7]) == "active":
        db.execute(text(
            "UPDATE direct_ship_authorization SET status='withdrawn',withdrawn_at=:now "
            "WHERE id=:id AND tenant_id=:t AND status='active'"
        ), {"now": withdrawn_at, "id": authorization_id, "t": tenant_id})
        from src.app.services.temporal_invalidation import invalidate_source_dependencies

        invalidate_source_dependencies(
            db, tenant_id=tenant_id, source_type="direct_ship_authorization",
            source_id=authorization_id, source_version=str(row[9]),
            reason="authorization_withdrawn",
        )
    return {"authorization_id": authorization_id, "tenant_id": tenant_id,
            "case_id": str(row[0]), "supplier_id": str(row[1]),
            "destination_token": str(row[2]), "jurisdiction": str(row[3]),
            "purpose": str(row[4]), "permitted_fields": json.loads(str(row[5])),
            "retention_until": str(row[6]), "status": "withdrawn",
            "authorized_by": str(row[8]), "authorized_at": str(row[9]),
            "audit_evidence_id": str(row[10]), "withdrawn_at": withdrawn_at,
            "withdrawn_by": str(actor_id)}


def get_direct_shipping_authorization(
    db, *, tenant_id: str, authorization_id: str,
) -> dict[str, Any] | None:
    row = db.execute(text(
        "SELECT case_id,supplier_id,destination_token,jurisdiction,purpose,permitted_fields_json,"
        "retention_until,status,authorized_by,authorized_at,withdrawn_at,audit_evidence_id "
        "FROM direct_ship_authorization WHERE id=:id AND tenant_id=:t"
    ), {"id": authorization_id, "t": tenant_id}).fetchone()
    if row is None:
        return None
    status = str(row[7])
    expiry = datetime.fromisoformat(str(row[6]).replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if status == "active" and expiry <= datetime.now(timezone.utc):
        status = "expired"
        db.execute(text(
            "UPDATE direct_ship_authorization SET status='expired' WHERE id=:id AND tenant_id=:t "
            "AND status='active'"
        ), {"id": authorization_id, "t": tenant_id})
    return {"authorization_id": authorization_id, "tenant_id": tenant_id,
            "case_id": str(row[0]), "supplier_id": str(row[1]),
            "destination_token": str(row[2]), "jurisdiction": str(row[3]),
            "purpose": str(row[4]), "permitted_fields": json.loads(str(row[5])),
            "retention_until": str(row[6]), "status": status,
            "authorized_by": str(row[8]), "authorized_at": str(row[9]),
            "withdrawn_at": row[10], "audit_evidence_id": str(row[11])}


def evaluate_fulfillment_route(
    *, requested_mode: str, policy_modes: Iterable[str], dispatch_days: tuple[int, int],
    transit_days: tuple[int, int], inspection_days: tuple[int, int],
    final_mile_days: tuple[int, int], buyer_destination: dict[str, Any],
    destination_token: str, pii_release_authorized: bool = False,
    warehouse_capacity_available: bool = True,
    privacy_authorization: dict[str, Any] | None = None,
    supplier_id: str | None = None,
    supplier_jurisdiction: str | None = None,
    supplier_capability: dict[str, Any] | None = None,
    required_capacity_units: int = 0,
    available_capacity_units: int | None = None,
    cross_dock_days: tuple[int, int] = (0, 0),
    split_shipments: Iterable[dict[str, Any]] | None = None,
    cost_components_cents: dict[str, int] | None = None,
    cost_currency: str | None = None,
) -> dict[str, Any]:
    """Evaluate one route without booking freight, releasing PII, or making a delivery promise."""
    mode = str(requested_mode or "").lower()
    allowed = {str(value).lower() for value in policy_modes}
    if mode not in MODES or mode not in allowed:
        return {"mode": mode, "status": "blocked", "state_prevented": "mode_not_authorized",
                "supplier_destination": {"destination_token": destination_token}}
    capability = dict(supplier_capability or {})
    capability_key = "direct_ship" if mode == "supplier_direct" else mode
    if capability and (
        str(capability.get("status") or "") != "verified" or not capability.get(capability_key)
    ):
        return {"mode": mode, "status": "blocked", "state_prevented": "supplier_capability_unverified",
                "supplier_destination": {"destination_token": destination_token}}
    capacity_ok = bool(warehouse_capacity_available)
    if available_capacity_units is not None:
        capacity_ok = capacity_ok and int(available_capacity_units) >= max(0, int(required_capacity_units))
    if mode in {"merchant_inspected", "cross_dock"} and not capacity_ok:
        return {"mode": mode, "status": "blocked",
                "state_prevented": (
                    "inspection_capacity_unavailable" if mode == "merchant_inspected"
                    else "cross_dock_capacity_unavailable"
                ),
                "supplier_destination": {"destination_token": destination_token}}
    privacy = None
    supplier_destination = {"destination_token": destination_token}
    if mode == "supplier_direct":
        authorization = dict(privacy_authorization or {})
        legacy_authorized = bool(pii_release_authorized) and not authorization
        valid = legacy_authorized
        if authorization:
            expiry = datetime.fromisoformat(str(authorization.get("retention_until") or "1970-01-01T00:00:00+00:00").replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            valid = (
                authorization.get("status") == "active"
                and str(authorization.get("destination_token")) == str(destination_token)
                and str(authorization.get("supplier_id")) == str(supplier_id)
                and str(authorization.get("jurisdiction")) == str(supplier_jurisdiction)
                and expiry > datetime.now(timezone.utc)
            )
        if not valid:
            return {"mode": mode, "status": "blocked", "state_prevented": "buyer_pii_release",
                    "supplier_destination": supplier_destination}
        permitted = set(authorization.get("permitted_fields") or buyer_destination.keys())
        supplier_destination = {key: value for key, value in buyer_destination.items() if key in permitted}
        privacy = {
            "authorization_id": authorization.get("authorization_id"),
            "jurisdiction": authorization.get("jurisdiction"),
            "purpose": authorization.get("purpose"),
            "retention_until": authorization.get("retention_until"),
            "fields_released": sorted(supplier_destination),
            "fields_withheld": sorted(set(buyer_destination) - set(supplier_destination)),
            "audit_evidence_id": authorization.get("audit_evidence_id"),
        }
    ranges = [_range(dispatch_days), _range(transit_days), _range(final_mile_days)]
    if mode == "merchant_inspected":
        ranges.insert(2, _range(inspection_days))
    elif mode == "cross_dock":
        ranges.insert(2, _range(cross_dock_days))
    shipments = [dict(item) for item in (split_shipments or [])]
    if mode == "split" and shipments:
        shipment_ranges = [_range(tuple(item.get("eta_days") or (0, 0))) for item in shipments]
        eta = {"min": min(value[0] for value in shipment_ranges),
               "max": max(value[1] for value in shipment_ranges)}
    else:
        eta = {"min": sum(value[0] for value in ranges), "max": sum(value[1] for value in ranges)}
    costs = {str(key): int(value) for key, value in sorted((cost_components_cents or {}).items())}
    if any(value < 0 for value in costs.values()):
        raise ValueError("negative_route_cost")
    return {"mode": mode, "status": "eligible", "state_prevented": None,
            "eta_days": eta, "eta_authority": "calculated_range_not_promise",
            "supplier_destination": supplier_destination,
            "requires_inspection": mode == "merchant_inspected",
            "return_owner": capability.get("returns_owner") or "unresolved",
            "supplier_capability_version": capability.get("version"),
            "capacity": {"required_units": max(0, int(required_capacity_units)),
                         "available_units": available_capacity_units, "sufficient": capacity_ok},
            "shipment_count": len(shipments) if mode == "split" else 1,
            "split_shipments": shipments if mode == "split" else [],
            "cost_to_serve": {"currency": str(cost_currency or "unknown").upper(),
                              "total_cents": sum(costs.values()), "components": costs},
            "privacy": privacy}


def normalize_supplier_schedule(*, requested_qty: int, internal_allocated_qty: int,
                                schedule_lines: Iterable[dict[str, Any]],
                                evidence_fresh: bool) -> dict[str, Any]:
    """Normalize supplier schedule lines and recompute the buyer-safe promise state.

    Supplier observations are never allowed to claim more than the unresolved quantity. Stale
    observations become unknown regardless of their textual status.
    """
    requested = max(0, int(requested_qty))
    internal = min(requested, max(0, int(internal_allocated_qty)))
    unresolved = max(0, requested - internal)
    if not evidence_fresh:
        return {"supplier_state": "unknown_stale", "supplier_confirmed_qty": 0,
                "covered_qty": internal, "shortfall_qty": unresolved,
                "promise_state": "unconfirmed", "alternatives_required": unresolved > 0,
                "buyer_message": (
                    f"{internal} of {requested} units are backed by current internal allocation. "
                    "Supplier availability is stale, so the remaining quantity is not confirmed."
                )}
    confirmed = backordered = rejected = 0
    confirmed_etas: list[str] = []
    for line in schedule_lines:
        state = str(line.get("status") or "").lower()
        if state not in LINE_STATES:
            continue
        quantity = max(0, int(line.get("quantity") or 0))
        if state in {"confirmed", "partial"}:
            accepted = min(quantity, max(0, unresolved - confirmed))
            confirmed += accepted
            if accepted and line.get("eta"):
                confirmed_etas.append(str(line["eta"]))
        elif state == "backordered":
            backordered += quantity
        elif state == "rejected":
            rejected += quantity
    covered = min(requested, internal + confirmed)
    shortfall = max(0, requested - covered)
    promise = "complete" if shortfall == 0 else ("partial" if covered > 0 else "unconfirmed")
    if promise == "complete":
        message = f"All {requested} units now have allocation evidence. Delivery timing remains subject to the stated route range."
    elif covered:
        message = f"We currently have evidence covering {covered} of {requested} units. We are checking alternatives for the remaining {shortfall}."
    else:
        message = f"We cannot currently confirm supply for the {requested} requested units. We are checking approved alternatives."
    return {"supplier_state": "confirmed" if confirmed else "not_confirmed",
            "supplier_confirmed_qty": confirmed, "internal_allocated_qty": internal,
            "covered_qty": covered, "shortfall_qty": shortfall, "backordered_qty": backordered,
            "rejected_qty": rejected, "confirmed_etas": sorted(set(confirmed_etas)),
            "promise_state": promise, "alternatives_required": shortfall > 0,
            "buyer_message": message}


def persist_route_proposal(db, *, tenant_id: str, case_id: str, destination_token: str,
                           requested_mode: str, policy_modes: Iterable[str],
                           dispatch_days: tuple[int, int], transit_days: tuple[int, int],
                           inspection_days: tuple[int, int], final_mile_days: tuple[int, int],
                           buyer_destination: dict[str, Any] | None = None,
                           pii_release_authorized: bool = False,
                           warehouse_capacity_available: bool = True,
                           privacy_authorization: dict[str, Any] | None = None,
                           supplier_id: str | None = None,
                           supplier_jurisdiction: str | None = None,
                           supplier_capability: dict[str, Any] | None = None,
                           required_capacity_units: int = 0,
                           available_capacity_units: int | None = None,
                           cross_dock_days: tuple[int, int] = (0, 0),
                           split_shipments: Iterable[dict[str, Any]] | None = None,
                           cost_components_cents: dict[str, int] | None = None,
                           cost_currency: str | None = None) -> dict[str, Any]:
    """Persist the exact policy inputs and ETA components without turning the range into a promise."""
    components = {
        "dispatch_days": list(dispatch_days), "transit_days": list(transit_days),
        "inspection_days": list(inspection_days), "final_mile_days": list(final_mile_days),
        "cross_dock_days": list(cross_dock_days),
        "warehouse_capacity_available": bool(warehouse_capacity_available),
        "required_capacity_units": int(required_capacity_units),
        "available_capacity_units": available_capacity_units,
        "policy_modes": sorted({str(value).lower() for value in policy_modes}),
        "supplier_id": supplier_id, "supplier_jurisdiction": supplier_jurisdiction,
        "supplier_capability": dict(supplier_capability or {}),
        "split_shipments": [dict(item) for item in (split_shipments or [])],
        "cost_components_cents": dict(cost_components_cents or {}),
        "cost_currency": cost_currency,
        "direct_ship_authorization_id": (privacy_authorization or {}).get("authorization_id"),
    }
    result = evaluate_fulfillment_route(
        requested_mode=requested_mode, policy_modes=components["policy_modes"],
        dispatch_days=dispatch_days, transit_days=transit_days,
        inspection_days=inspection_days, final_mile_days=final_mile_days,
        buyer_destination=dict(buyer_destination or {}), destination_token=destination_token,
        pii_release_authorized=pii_release_authorized,
        warehouse_capacity_available=warehouse_capacity_available,
        privacy_authorization=privacy_authorization, supplier_id=supplier_id,
        supplier_jurisdiction=supplier_jurisdiction, supplier_capability=supplier_capability,
        required_capacity_units=required_capacity_units,
        available_capacity_units=available_capacity_units,
        cross_dock_days=cross_dock_days, split_shipments=split_shipments,
        cost_components_cents=cost_components_cents, cost_currency=cost_currency,
    )
    material = {"case_id": case_id, "destination_token": destination_token,
                "mode": requested_mode, "components": components,
                "pii_release_authorized": bool(pii_release_authorized)}
    version = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    existing = db.execute(text(
        "SELECT id FROM fulfillment_route_proposal WHERE tenant_id=:t AND case_id=:case "
        "AND proposal_version=:version"
    ), {"t": tenant_id, "case": case_id, "version": version}).fetchone()
    proposal_id = str(existing[0]) if existing else str(uuid.uuid4())
    if not existing:
        eta = result.get("eta_days") or {}
        db.execute(text(
            "INSERT INTO fulfillment_route_proposal "
            "(id,tenant_id,case_id,proposal_version,mode,status,destination_token,eta_min_days,"
            "eta_max_days,components_json,state_prevented,pii_release_authorized,created_at) VALUES "
            "(:id,:t,:case,:version,:mode,:status,:destination,:eta_min,:eta_max,:components,"
            ":prevented,:pii,:now)"
        ), {"id": proposal_id, "t": tenant_id, "case": case_id, "version": version,
            "mode": str(requested_mode).lower(), "status": result["status"],
            "destination": destination_token, "eta_min": eta.get("min"), "eta_max": eta.get("max"),
            "components": json.dumps(components, sort_keys=True),
            "prevented": result.get("state_prevented"), "pii": bool(pii_release_authorized),
            "now": datetime.now(timezone.utc).isoformat()})
    if privacy_authorization and privacy_authorization.get("authorization_id"):
        from src.app.services.temporal_invalidation import register_derived_dependency

        register_derived_dependency(
            db, tenant_id=tenant_id, source_type="direct_ship_authorization",
            source_id=str(privacy_authorization["authorization_id"]),
            source_version=str(privacy_authorization.get("authorized_at") or "unknown"),
            derived_type="fulfillment_route_proposal", derived_id=proposal_id,
        )
    return {"proposal_id": proposal_id, "proposal_version": version,
            "idempotent": bool(existing), "components": components, **result}
