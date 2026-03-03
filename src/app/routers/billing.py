from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_OWNER, ROLE_MERCHANT
from src.app.services.billing import (
    link_tenant_stripe,
    list_billing_plans,
    onboard_pilot_tenant,
    provision_tenant_core,
    record_meter_event,
    usage_summary,
)
from src.app.connectors.accounting.xero import XeroConnector
from src.app.services.platform_regions import region_readiness
from src.app.security.oob_verification import get_verification


router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _enforce_oob_for_beneficiary_change(payload: Dict[str, Any]) -> None:
    """§14: require out-of-band verification for any beneficiary bank change."""
    p = payload or {}
    old_fp = str(p.get("bank_fingerprint") or "").strip()
    new_fp = str(p.get("proposed_bank_fingerprint") or "").strip()
    beneficiary_changed = bool(
        (old_fp and new_fp and old_fp != new_fp)
        or bool(p.get("beneficiary_changed"))
        or bool(p.get("bank_account_changed"))
    )
    if not beneficiary_changed:
        return
    # Explicit OOB boolean short-circuit for trusted internal callers.
    if bool(p.get("oob_verified")):
        return
    request_id = str(p.get("oob_request_id") or "").strip()
    if not request_id:
        raise HTTPException(status_code=409, detail="oob_verification_required_for_beneficiary_change")
    rec = get_verification(request_id)
    if not rec or str(rec.get("status") or "") != "confirmed":
        raise HTTPException(status_code=409, detail="oob_verification_not_confirmed")


@router.post("/admin/pilots/onboard")
def onboard_pilot(
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tenant_id = str((payload or {}).get("tenant_id") or "").strip()
    company_name = str((payload or {}).get("company_name") or "").strip()
    contact_email = str((payload or {}).get("contact_email") or "").strip()
    vertical = str((payload or {}).get("vertical") or "").strip() or None
    if not tenant_id or not company_name or not contact_email:
        raise HTTPException(status_code=400, detail="tenant_id, company_name, contact_email required")
    return onboard_pilot_tenant(
        tenant_id=tenant_id,
        company_name=company_name,
        contact_email=contact_email,
        vertical=vertical,
    )


@router.post("/admin/tenants/{tenant_id}/stripe/link")
def link_stripe_billing(
    tenant_id: str,
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    customer_id = str((payload or {}).get("stripe_customer_id") or "").strip()
    sub_item_id = str((payload or {}).get("stripe_subscription_item_id") or "").strip()
    meter_key = str((payload or {}).get("meter_key") or "").strip() or None
    if not customer_id or not sub_item_id:
        raise HTTPException(status_code=400, detail="stripe_customer_id and stripe_subscription_item_id required")
    return link_tenant_stripe(
        tenant_id=str(tenant_id),
        customer_id=customer_id,
        subscription_item_id=sub_item_id,
        meter_key=meter_key,
    )


@router.post("/meter-event")
def meter_event(
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tenant_id = str((payload or {}).get("tenant_id") or "").strip()
    metric = str((payload or {}).get("metric") or "").strip()
    quantity = float((payload or {}).get("quantity") or 0.0)
    source = str((payload or {}).get("source") or "").strip() or None
    metadata = (payload or {}).get("metadata") if isinstance((payload or {}).get("metadata"), dict) else {}
    if not tenant_id or not metric:
        raise HTTPException(status_code=400, detail="tenant_id and metric required")
    return record_meter_event(
        tenant_id=tenant_id,
        metric=metric,
        quantity=quantity,
        source=source,
        metadata=metadata,
    )


@router.get("/admin/usage")
def billing_usage(
    tenant_id: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return usage_summary(tenant_id=tenant_id, days=days)


@router.get("/admin/plans")
def billing_plans(
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return list_billing_plans()


@router.post("/admin/tenants/provision")
def provision_tenant(
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tenant_id = str((payload or {}).get("tenant_id") or "").strip()
    plan_id = str((payload or {}).get("plan_id") or "starter").strip().lower()
    home_region = str((payload or {}).get("home_region") or "").strip().lower()
    limits = (payload or {}).get("limits") if isinstance((payload or {}).get("limits"), dict) else {}
    if not tenant_id or not home_region:
        raise HTTPException(status_code=400, detail="tenant_id and home_region required")
    topo = region_readiness()
    known_regions = {
        str((r or {}).get("id") or "").strip().lower()
        for r in (topo.get("regions") or [])
        if isinstance(r, dict)
    }
    if home_region not in known_regions:
        raise HTTPException(status_code=400, detail="home_region_not_allowed_by_topology")
    return provision_tenant_core(
        tenant_id=tenant_id,
        plan_id=plan_id,
        home_region=home_region,
        limits=limits,
    )


@router.post("/accounting/xero/credit-note")
def xero_credit_note(
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _enforce_oob_for_beneficiary_change(payload)
    connector = XeroConnector()
    return connector.push_credit_note(
        decision_id=str((payload or {}).get("decision_id") or ""),
        amount=float((payload or {}).get("amount") or 0.0),
        reason=str((payload or {}).get("reason") or "refund"),
    )


@router.post("/accounting/xero/invoice")
def xero_invoice(
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _enforce_oob_for_beneficiary_change(payload)
    connector = XeroConnector()
    return connector.push_invoice(dict(payload or {}))


@router.post("/accounting/xero/purchase-order")
def xero_purchase_order(
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _enforce_oob_for_beneficiary_change(payload)
    connector = XeroConnector()
    return connector.push_purchase_order(dict(payload or {}))


@router.post("/accounting/xero/inventory-adjustment")
def xero_inventory_adjustment(
    payload: Dict[str, Any] = Body(default={}),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    connector = XeroConnector()
    sku = str((payload or {}).get("sku") or "").strip()
    qty = int((payload or {}).get("qty") or 0)
    reason = str((payload or {}).get("reason") or "adjustment")
    if not sku:
        raise HTTPException(status_code=400, detail="sku required")
    return connector.push_inventory_adjustment(sku=sku, qty=qty, reason=reason)


@router.get("/accounting/xero/reconcile")
def xero_reconcile(
    start: str = Query(...),
    end: str = Query(...),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    connector = XeroConnector()
    return connector.reconcile_payments((start, end))

