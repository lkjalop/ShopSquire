"""Cart-mutation plan endpoints (V2 cart milestone C1 — GPT-5.6 review-5 recommended shape).

The frontend confirmation card's other half: a confirm-tier plan proposed by the chat lane is
APPLIED here — POST /api/v1/cart/mutations/{plan_id}/apply — through the same transactional
service the auto tier uses (idempotent CAS, stale-cart guard, all-or-nothing, undo stash).
GET exposes a plan for rendering the card. Role-gated identically to the cart REST surface."""
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.app.deps import get_redis
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.cart_mutation_service import apply_plan, get_plan

router = APIRouter(prefix="/api/v1/cart/mutations", tags=["cart-mutations"])


class ApplyPayload(BaseModel):
    uid: str
    tenant_id: str = "default"


@router.post("/{plan_id}/apply")
def apply_mutation(plan_id: str, payload: ApplyPayload, redis=Depends(get_redis),
                   role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    out = apply_plan(plan_id, tenant_id=payload.tenant_id, uid=payload.uid, redis=redis)
    status = out.get("status")
    if status == "not_found":
        raise HTTPException(status_code=404, detail={"error": "plan_not_found", "plan_id": plan_id})
    if status == "forbidden":
        raise HTTPException(status_code=403, detail={"error": "plan_scope_mismatch", "plan_id": plan_id})
    # applied / already_applied / rejected / stale_cart / expired / conflict are all HONEST
    # 200-level outcomes the card renders — the plan lifecycle, not transport errors.
    return out


@router.get("/{plan_id}")
def get_mutation(plan_id: str, uid: str, tenant_id: str = "default",
                 role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    row = get_plan(plan_id)
    if row is None or row["uid"] != str(uid or "") or row["tenant_id"] != str(tenant_id or "default"):
        # scope mismatch reads as absent — a plan id must not leak other shoppers' cart contents
        raise HTTPException(status_code=404, detail={"error": "plan_not_found", "plan_id": plan_id})
    return {"plan_id": row["plan_id"], "risk": row["risk"], "status": row["status"],
            "plan": row["plan"], "expires_at": row["expires_at"], "result": row["result"]}
