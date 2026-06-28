"""KYV (Know-Your-Vendor) onboarding + lifecycle — owner control plane.

The autonomous-RFQ-send trust gate (WS-C) requires a VERIFIED, low/medium-risk kyv_vendors record for the
recipient domain before it will send without a human. This router is how those records get created and
maintained: register a vendor (ABN/ACN validated), verify it, set its contact email, suspend/revoke, and
review the ones flagged for re-review. OWNER/DEVELOPER-gated — vendor trust is a sensitive control.

All handlers delegate to src.app.security.kyv_registry (the single source of truth + audited writes); this
router is the thin HTTP surface. Tenant comes from the X-Tenant-Id header (default 'default')."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from src.app.security import kyv_registry as kyv
from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, require_role
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/admin/kyv", tags=["kyv"])

_ADMIN = [ROLE_OWNER, ROLE_DEVELOPER]


def _tenant(x: Optional[str]) -> str:
    return (x or "default").strip() or "default"


class RegisterVendorBody(BaseModel):
    legal_name: str
    registration_number: Optional[str] = None
    registration_type: Optional[str] = None   # abn | acn (auto-detected when omitted)
    trading_name: Optional[str] = None
    verified_domain: Optional[str] = None      # the email domain the RFQ recipient must match
    contact_email: Optional[str] = None
    risk_tier: str = "medium"                  # low | medium | high | critical (autonomy needs ≤ medium)
    notes: Optional[str] = None


class StatusBody(BaseModel):
    status: str                                # pending | verified | suspended | revoked
    notes: Optional[str] = None


class ContactEmailBody(BaseModel):
    domain: str
    contact_email: str


@router.post("/vendors")
def register_vendor(body: RegisterVendorBody, role: str = Depends(require_role(_ADMIN)),
                    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    """Register a vendor (status starts 'pending' unless KYV_AUTO_VERIFY + a valid registration). Returns
    the created record or a 400 with the validation reason (e.g. an invalid ABN/ACN)."""
    res = kyv.register_vendor(
        tenant_id=_tenant(x_tenant_id), legal_name=body.legal_name,
        registration_number=body.registration_number, registration_type=body.registration_type,
        trading_name=body.trading_name, verified_domain=body.verified_domain,
        contact_email=body.contact_email, risk_tier=body.risk_tier, notes=body.notes)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "registration_failed"))
    return res


@router.get("/vendors/review")
def vendors_needing_review(role: str = Depends(require_role(_ADMIN)),
                           x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    return {"vendors": kyv.list_vendors_needing_review(tenant_id=_tenant(x_tenant_id))}


@router.get("/vendors/by-domain/{domain}")
def vendor_by_domain(domain: str, role: str = Depends(require_role(_ADMIN)),
                     x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    rec = kyv.lookup_vendor_by_domain(tenant_id=_tenant(x_tenant_id), domain=domain)
    if not rec:
        raise HTTPException(status_code=404, detail="vendor_not_found")
    return rec


@router.post("/vendors/{vendor_id}/verify")
def verify_vendor(vendor_id: str, role: str = Depends(require_role(_ADMIN)),
                  x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    """Mark a vendor verified — the prerequisite for the autonomous-send trust gate to accept its domain."""
    ok = kyv.update_vendor_status(tenant_id=_tenant(x_tenant_id), vendor_id=vendor_id, status="verified")
    if not ok:
        raise HTTPException(status_code=404, detail="vendor_not_found_or_invalid_status")
    return {"ok": True, "vendor_id": vendor_id, "status": "verified"}


@router.post("/vendors/{vendor_id}/status")
def set_vendor_status(vendor_id: str, body: StatusBody, role: str = Depends(require_role(_ADMIN)),
                      x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    """Transition status (e.g. suspend/revoke a vendor → instantly removes autonomous-send trust)."""
    ok = kyv.update_vendor_status(tenant_id=_tenant(x_tenant_id), vendor_id=vendor_id,
                                  status=body.status, notes=body.notes)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid_status_or_vendor")
    return {"ok": True, "vendor_id": vendor_id, "status": body.status.lower()}


@router.post("/vendors/contact-email")
def set_contact_email(body: ContactEmailBody, role: str = Depends(require_role(_ADMIN)),
                      x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    """Backfill a vendor's contact email (matched by domain) so the RFQ resolves a real recipient address."""
    ok = kyv.set_vendor_contact_email(tenant_id=_tenant(x_tenant_id), domain=body.domain,
                                      contact_email=body.contact_email)
    return {"ok": bool(ok), "domain": body.domain.strip().lower()}


@router.post("/vendors/{vendor_id}/reviewed")
def mark_reviewed(vendor_id: str, role: str = Depends(require_role(_ADMIN)),
                  x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> Dict[str, Any]:
    ok = kyv.mark_reviewed(tenant_id=_tenant(x_tenant_id), vendor_id=vendor_id)
    if not ok:
        raise HTTPException(status_code=404, detail="vendor_not_found")
    return {"ok": True, "vendor_id": vendor_id}
