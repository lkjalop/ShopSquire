"""Cart-mutation plan endpoints (V2 cart milestone C1 — GPT-5.6 review-5 recommended shape).

The frontend confirmation card's other half: a confirm-tier plan proposed by the chat lane is
APPLIED here — POST /api/v1/cart/mutations/{plan_id}/apply — through the same transactional
service the auto tier uses (idempotent CAS, stale-cart guard, all-or-nothing, undo stash).
GET exposes a plan for rendering the card. Role-gated identically to the cart REST surface."""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from src.app.deps import get_redis
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.cart_mutation_service import apply_plan, get_plan, reject_plan

router = APIRouter(prefix="/api/v1/cart/mutations", tags=["cart-mutations"])


def _tenant(header_value: Optional[str]) -> str:
    """TENANT FROM THE REQUEST, NOT THE BODY (review-6 #5): the X-Tenant-Id header is the app-wide
    tenant convention (main.py, store_profile_middleware, the recommend/suggest surface that
    PROPOSED the plan). A client can no longer name an arbitrary tenant in the JSON body to probe
    or apply another tenant's plan."""
    return str(header_value or "default")


class ApplyPayload(BaseModel):
    uid: str
    session_epoch: Optional[str] = None
    # tenant_id REMOVED from the body (review-6 #5) — derived from X-Tenant-Id below.


@router.post("/{plan_id}/apply")
def apply_mutation(plan_id: str, payload: ApplyPayload, redis=Depends(get_redis),
                   x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
                   role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    out = apply_plan(plan_id, tenant_id=_tenant(x_tenant_id), uid=payload.uid, redis=redis)
    if out.get("status") == "applied" and any(
        row.get("action") == "clear_all" for row in (out.get("applied") or [])
        if isinstance(row, dict)
    ):
        from src.app.services.cart_session_state import clear_cart_commercial_state

        clear_cart_commercial_state(
            redis,
            uid=payload.uid,
            tenant_id=_tenant(x_tenant_id),
            session_epoch=payload.session_epoch,
        )
    status = out.get("status")
    if status == "not_found":
        raise HTTPException(status_code=404, detail={"error": "plan_not_found", "plan_id": plan_id})
    if status == "forbidden":
        raise HTTPException(status_code=403, detail={"error": "plan_scope_mismatch", "plan_id": plan_id})
    # applied / already_applied / rejected / stale_cart / expired / conflict are all HONEST
    # 200-level outcomes the card renders — the plan lifecycle, not transport errors.
    return out


@router.post("/{plan_id}/reject")
def reject_mutation(plan_id: str, payload: ApplyPayload,
                    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
                    role: str = Depends(require_role(
                        [ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]
                    ))) -> Dict:
    out = reject_plan(plan_id, tenant_id=_tenant(x_tenant_id), uid=payload.uid)
    if out.get("status") == "not_found":
        raise HTTPException(status_code=404, detail={"error": "plan_not_found", "plan_id": plan_id})
    if out.get("status") == "forbidden":
        raise HTTPException(status_code=403, detail={"error": "plan_scope_mismatch", "plan_id": plan_id})
    return out


@router.get("/{plan_id}")
def get_mutation(plan_id: str, uid: str,
                 x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
                 role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    row = get_plan(plan_id)
    if row is None or row["uid"] != str(uid or "") or row["tenant_id"] != _tenant(x_tenant_id):
        # scope mismatch reads as absent — a plan id must not leak other shoppers' cart contents
        raise HTTPException(status_code=404, detail={"error": "plan_not_found", "plan_id": plan_id})
    return {"plan_id": row["plan_id"], "risk": row["risk"], "status": row["status"],
            "plan": row["plan"], "expires_at": row["expires_at"], "result": row["result"]}
