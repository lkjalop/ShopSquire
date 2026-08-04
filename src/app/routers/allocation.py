"""Operator API for the shadow demand/allocation and governed sourcing boundary."""
from __future__ import annotations

from typing import Any

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.app.models.db import db_session
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role_or_oidc
from src.app.services.demand_allocation import (
    allocate_committed,
    allocation_shadow_parity,
    allocation_workbench,
    apply_supplier_schedule,
    apply_supplier_schedule_to_batch,
    buyer_procurement_context,
    consolidate_shortfalls,
    create_sourcing_wave,
    materialize_governed_rfq_for_batch,
    materialize_governed_rfq_for_wave,
    sync_authoritative_location_atp,
)
from src.app.services.fulfillment.route_policy import (
    authorize_direct_shipping,
    get_direct_shipping_authorization,
    persist_route_proposal,
    withdraw_direct_shipping_authorization,
)
from src.app.services.supplier_sourcing_authority import load_sourcing_admission_context


router = APIRouter(prefix="/api/v1/admin/allocation", tags=["admin-allocation"])
buyer_router = APIRouter(prefix="/api/v1/fulfillment", tags=["fulfillment-allocation"])
_OPERATOR = [ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER]


def _tenant() -> str:
    return str(current_tenant_id() or "default")


@buyer_router.get("/procurement-context/{case_id}")
def procurement_context(case_id: str, request: Request, uid: str | None = Query(default=None)) -> dict[str, Any]:
    from src.app.security.buyer_principal import resolve_buyer_principal

    principal = resolve_buyer_principal(request, supplied_uid=uid)
    if principal is None:
        raise HTTPException(status_code=401, detail="buyer_identity_required")
    buyer_hash = hashlib.sha256(str(principal.subject).encode("utf-8")).hexdigest()
    with db_session() as db:
        result = buyer_procurement_context(
            db, tenant_id=str(principal.tenant_id), case_id=case_id, buyer_ref_hash=buyer_hash,
        )
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="procurement_context_not_found")
    return result


class AtpSyncBody(BaseModel):
    source: str = Field(min_length=1, max_length=120)


class AllocateBody(BaseModel):
    sku: str = Field(min_length=1, max_length=180)
    uom: str = Field(default="each", min_length=1, max_length=80)
    location_id: str = Field(min_length=1, max_length=180)


class ConsolidateBody(BaseModel):
    supplier_id: str | None = Field(default=None, max_length=180)
    supplier_facility_id: str | None = Field(default=None, max_length=180)
    window_ends_at: str = Field(min_length=1, max_length=80)
    urgency_bypass: bool = False


class SupplierScheduleBody(BaseModel):
    supplier_id: str = Field(min_length=1, max_length=180)
    evidence_id: str = Field(min_length=1, max_length=240)
    schedule_lines: list[dict[str, Any]]
    observed_at: str = Field(min_length=1, max_length=80)
    expires_at: str | None = Field(default=None, max_length=80)


class SourcingWaveBody(BaseModel):
    supplier_id: str = Field(min_length=1, max_length=180)
    supplier_facility_id: str = Field(min_length=1, max_length=180)
    currency: str = Field(min_length=3, max_length=3)
    incoterm: str = Field(min_length=2, max_length=20)
    merchant_destination_id: str = Field(min_length=1, max_length=180)
    window_ends_at: str = Field(min_length=1, max_length=80)
    batch_ids: list[str] = Field(min_length=1, max_length=200)
    standalone_freight_cents: int = Field(ge=0)
    consolidated_freight_cents: int = Field(ge=0)
    handling_cents: int = Field(default=0, ge=0)


class DirectShipAuthorizationBody(BaseModel):
    case_id: str = Field(min_length=1, max_length=180)
    supplier_id: str = Field(min_length=1, max_length=180)
    destination_token: str = Field(min_length=1, max_length=240)
    jurisdiction: str = Field(min_length=2, max_length=80)
    purpose: str = Field(default="deliver_order", min_length=1, max_length=120)
    permitted_fields: list[str] = Field(min_length=1, max_length=20)
    retention_until: str = Field(min_length=1, max_length=80)
    audit_evidence_id: str = Field(min_length=1, max_length=240)


class RouteProposalBody(BaseModel):
    case_id: str = Field(min_length=1, max_length=180)
    destination_token: str = Field(min_length=1, max_length=240)
    requested_mode: str
    policy_modes: list[str]
    dispatch_days: tuple[int, int]
    transit_days: tuple[int, int]
    inspection_days: tuple[int, int] = (0, 0)
    final_mile_days: tuple[int, int]
    pii_release_authorized: bool = False
    warehouse_capacity_available: bool = True
    direct_ship_authorization_id: str | None = Field(default=None, max_length=180)
    supplier_id: str | None = Field(default=None, max_length=180)
    supplier_jurisdiction: str | None = Field(default=None, max_length=80)
    supplier_capability: dict[str, Any] = Field(default_factory=dict)
    required_capacity_units: int = Field(default=0, ge=0)
    available_capacity_units: int | None = Field(default=None, ge=0)
    cross_dock_days: tuple[int, int] = (0, 0)
    split_shipments: list[dict[str, Any]] = Field(default_factory=list)
    cost_components_cents: dict[str, int] = Field(default_factory=dict)
    cost_currency: str | None = Field(default=None, min_length=3, max_length=3)


@router.get("/workbench")
def workbench(sku: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500),
              role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    with db_session() as db:
        return allocation_workbench(db, tenant_id=_tenant(), sku=sku, limit=limit)


@router.post("/atp/sync")
def sync_atp(body: AtpSyncBody,
             role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    with db_session() as db:
        result = sync_authoritative_location_atp(db, tenant_id=_tenant(), source=body.source)
        db.commit()
        return result


@router.post("/allocate")
def allocate(body: AllocateBody,
             role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    with db_session() as db:
        result = allocate_committed(db, tenant_id=_tenant(), sku=body.sku, uom=body.uom,
                                    location_id=body.location_id)
        db.commit()
        return result


@router.get("/parity")
def parity(case_id: str | None = Query(default=None),
           role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    with db_session() as db:
        result = allocation_shadow_parity(db, tenant_id=_tenant(), case_id=case_id)
        db.commit()
        return result


@router.post("/sourcing/consolidate")
def consolidate(body: ConsolidateBody,
                role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    with db_session() as db:
        admission = None
        if body.supplier_id and body.supplier_facility_id:
            admission = load_sourcing_admission_context(
                db, tenant_id=_tenant(), supplier_id=body.supplier_id,
                supplier_facility_id=body.supplier_facility_id,
            )
            if admission["status"] != "ready":
                return {
                    "batches": [{
                        "status": "blocked", "reason": "supplier_authority_unavailable",
                        "reason_codes": admission["reason_codes"],
                        "state_prevented": "new_supplier_request",
                    }],
                    "supplier_authority": admission["evidence"],
                    "external_action": "none",
                }
        batches = consolidate_shortfalls(
            db, tenant_id=_tenant(), supplier_id=body.supplier_id,
            window_ends_at=body.window_ends_at, urgency_bypass=body.urgency_bypass,
            backpressure_policy=admission["policy"] if admission else None,
            supplier_queue_state=admission["state"] if admission else None,
        )
        db.commit()
        return {
            "batches": batches,
            "supplier_authority": admission["evidence"] if admission else {
                "status": "not_evaluated", "reason": "supplier_facility_not_supplied",
            },
            "external_action": "none",
        }


@router.post("/sourcing/{batch_id}/draft-rfq")
def draft_rfq(batch_id: str, role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    try:
        with db_session() as db:
            result = materialize_governed_rfq_for_batch(db, tenant_id=_tenant(), batch_id=batch_id)
            db.commit()
            return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sourcing/waves")
def sourcing_wave(body: SourcingWaveBody,
                  role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    with db_session() as db:
        result = create_sourcing_wave(
            db, tenant_id=_tenant(), supplier_id=body.supplier_id,
            supplier_facility_id=body.supplier_facility_id, currency=body.currency,
            incoterm=body.incoterm, merchant_destination_id=body.merchant_destination_id,
            window_ends_at=body.window_ends_at, batch_ids=body.batch_ids,
            standalone_freight_cents=body.standalone_freight_cents,
            consolidated_freight_cents=body.consolidated_freight_cents,
            handling_cents=body.handling_cents,
        )
        db.commit()
        return result


@router.post("/sourcing/waves/{wave_id}/draft-rfq")
def draft_wave_rfq(
    wave_id: str, role: str = Depends(require_role_or_oidc(_OPERATOR)),
) -> dict[str, Any]:
    _ = role
    try:
        with db_session() as db:
            result = materialize_governed_rfq_for_wave(
                db, tenant_id=_tenant(), wave_id=wave_id,
            )
            db.commit()
            return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@buyer_router.post("/direct-ship-authorizations")
def create_direct_ship_authorization(
    body: DirectShipAuthorizationBody, request: Request, uid: str | None = Query(default=None),
) -> dict[str, Any]:
    from src.app.security.buyer_principal import resolve_buyer_principal

    principal = resolve_buyer_principal(request, supplied_uid=uid)
    if principal is None:
        raise HTTPException(status_code=401, detail="buyer_identity_required")
    buyer_hash = hashlib.sha256(str(principal.subject).encode("utf-8")).hexdigest()
    with db_session() as db:
        context = buyer_procurement_context(
            db, tenant_id=str(principal.tenant_id), case_id=body.case_id,
            buyer_ref_hash=buyer_hash,
        )
        if context["status"] == "not_found":
            raise HTTPException(status_code=404, detail="buyer_procurement_case_not_found")
        result = authorize_direct_shipping(
            db, tenant_id=str(principal.tenant_id), case_id=body.case_id,
            supplier_id=body.supplier_id, destination_token=body.destination_token,
            jurisdiction=body.jurisdiction, purpose=body.purpose,
            permitted_fields=body.permitted_fields, retention_until=body.retention_until,
            authorized_by=buyer_hash, audit_evidence_id=body.audit_evidence_id,
        )
        db.commit()
        result.pop("authorized_by", None)
        return result


@buyer_router.delete("/direct-ship-authorizations/{authorization_id}")
def revoke_direct_ship_authorization(
    authorization_id: str, request: Request, uid: str | None = Query(default=None),
) -> dict[str, Any]:
    from src.app.security.buyer_principal import resolve_buyer_principal

    principal = resolve_buyer_principal(request, supplied_uid=uid)
    if principal is None:
        raise HTTPException(status_code=401, detail="buyer_identity_required")
    buyer_hash = hashlib.sha256(str(principal.subject).encode("utf-8")).hexdigest()
    with db_session() as db:
        current = get_direct_shipping_authorization(
            db, tenant_id=str(principal.tenant_id), authorization_id=authorization_id,
        )
        if current is None or current.get("authorized_by") != buyer_hash:
            raise HTTPException(status_code=404, detail="direct_ship_authorization_not_found")
        result = withdraw_direct_shipping_authorization(
            db, tenant_id=str(principal.tenant_id), authorization_id=authorization_id,
            actor_id=buyer_hash,
        )
        db.commit()
        result.pop("authorized_by", None)
        result.pop("withdrawn_by", None)
        return result


@router.post("/demands/{demand_id}/supplier-schedule")
def supplier_schedule(demand_id: str, body: SupplierScheduleBody,
                      role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    try:
        with db_session() as db:
            result = apply_supplier_schedule(
                db, tenant_id=_tenant(), demand_id=demand_id, supplier_id=body.supplier_id,
                evidence_id=body.evidence_id, schedule_lines=body.schedule_lines,
                observed_at=body.observed_at, expires_at=body.expires_at,
            )
            db.commit()
            return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sourcing/{batch_id}/supplier-schedule")
def supplier_batch_schedule(batch_id: str, body: SupplierScheduleBody,
                            role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    try:
        with db_session() as db:
            result = apply_supplier_schedule_to_batch(
                db, tenant_id=_tenant(), batch_id=batch_id, supplier_id=body.supplier_id,
                evidence_id=body.evidence_id, schedule_lines=body.schedule_lines,
                observed_at=body.observed_at, expires_at=body.expires_at,
            )
            db.commit()
            return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/routes")
def route_proposal(body: RouteProposalBody,
                   role: str = Depends(require_role_or_oidc(_OPERATOR))) -> dict[str, Any]:
    _ = role
    with db_session() as db:
        privacy_authorization = None
        if body.direct_ship_authorization_id:
            privacy_authorization = get_direct_shipping_authorization(
                db, tenant_id=_tenant(), authorization_id=body.direct_ship_authorization_id,
            )
        result = persist_route_proposal(
            db, tenant_id=_tenant(), case_id=body.case_id,
            destination_token=body.destination_token, requested_mode=body.requested_mode,
            policy_modes=body.policy_modes, dispatch_days=body.dispatch_days,
            transit_days=body.transit_days, inspection_days=body.inspection_days,
            final_mile_days=body.final_mile_days, buyer_destination={},
            pii_release_authorized=body.pii_release_authorized,
            warehouse_capacity_available=body.warehouse_capacity_available,
            privacy_authorization=privacy_authorization, supplier_id=body.supplier_id,
            supplier_jurisdiction=body.supplier_jurisdiction,
            supplier_capability=body.supplier_capability,
            required_capacity_units=body.required_capacity_units,
            available_capacity_units=body.available_capacity_units,
            cross_dock_days=body.cross_dock_days, split_shipments=body.split_shipments,
            cost_components_cents=body.cost_components_cents,
            cost_currency=body.cost_currency,
        )
        db.commit()
        return result
