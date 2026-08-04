"""Tenant-scoped operator queue for the canonical escalation lifecycle."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.app.models.db import get_db
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role_or_oidc
from src.app.services.case_escalation import (
    get_escalation,
    list_escalation_timeline,
    list_open_escalations,
    transition_escalation,
)
from src.app.services.case_escalation_projection import (
    list_escalation_projections,
    project_existing_escalation_sources,
)


router = APIRouter(prefix="/api/v1/admin/escalations", tags=["admin-escalations"])
_OPERATOR = [ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER]


class EscalationTransitionBody(BaseModel):
    to_state: str = Field(min_length=1, max_length=40)
    idempotency_key: str = Field(min_length=1, max_length=240)
    reason: str = Field(default="", max_length=500)
    assigned_operator_id: str | None = Field(default=None, max_length=240)
    final_disposition: str | None = Field(default=None, max_length=240)
    resulting_amendment_id: str | None = Field(default=None, max_length=240)


@router.get("")
def escalation_queue(
    db=Depends(get_db),
    _role: str = Depends(require_role_or_oidc(_OPERATOR)),
) -> dict[str, Any]:
    tenant_id = str(current_tenant_id())
    return {
        "tenant_id": tenant_id,
        "authority": "canonical_case_escalation",
        "items": list_open_escalations(db, tenant_id=tenant_id),
    }


@router.post("/project-existing")
def project_existing(
    db=Depends(get_db),
    role: str = Depends(require_role_or_oidc(_OPERATOR)),
) -> dict[str, Any]:
    return project_existing_escalation_sources(
        db,
        tenant_id=str(current_tenant_id()),
        actor_id=role,
    )


@router.get("/{escalation_id}")
def escalation_detail(
    escalation_id: str,
    db=Depends(get_db),
    _role: str = Depends(require_role_or_oidc(_OPERATOR)),
) -> dict[str, Any]:
    tenant_id = str(current_tenant_id())
    escalation = get_escalation(db, tenant_id=tenant_id, escalation_id=escalation_id)
    if not escalation:
        raise HTTPException(status_code=404, detail="escalation_not_found")
    return {
        "escalation": escalation,
        "timeline": list_escalation_timeline(
            db, tenant_id=tenant_id, escalation_id=escalation_id
        ),
        "projections": list_escalation_projections(
            db, tenant_id=tenant_id, escalation_id=escalation_id
        ),
    }


@router.post("/{escalation_id}/transition")
def transition(
    escalation_id: str,
    body: EscalationTransitionBody,
    db=Depends(get_db),
    role: str = Depends(require_role_or_oidc(_OPERATOR)),
) -> dict[str, Any]:
    tenant_id = str(current_tenant_id())
    result = transition_escalation(
        db,
        tenant_id=tenant_id,
        escalation_id=escalation_id,
        to_state=body.to_state,
        actor_type="operator",
        actor_id=body.assigned_operator_id or role,
        idempotency_key=body.idempotency_key,
        reason=body.reason,
        assigned_operator_id=body.assigned_operator_id,
        final_disposition=body.final_disposition,
        resulting_amendment_id=body.resulting_amendment_id,
    )
    if not result.get("ok"):
        if result.get("reason") == "escalation_not_found":
            raise HTTPException(status_code=404, detail="escalation_not_found")
        raise HTTPException(status_code=409, detail=str(result.get("reason") or "transition_rejected"))
    return result
