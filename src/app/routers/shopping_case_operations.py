"""Authenticated operational observations for revisioned shopping cases."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select

from src.app.models.db import get_db
from src.app.models.orm import ShoppingCase
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.shopping_case_operational_observations import (
    OperationalObservationInput,
    record_case_operational_observation,
)
from src.app.services.operational_connector_registry import (
    project_operational_connector_health,
)


router = APIRouter(prefix="/api/v1/shopping-cases", tags=["shopping-case-operations"])


@router.get("/operational-connectors/health")
def operational_connector_health(
    _role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER, ROLE_MERCHANT])),
    db=Depends(get_db),
):
    """Operator truth: enrollment and observed health are separate facts."""

    tenant_id = str(current_tenant_id() or "default").strip() or "default"
    return project_operational_connector_health(db, tenant_id=tenant_id)


@router.post("/{case_id}/operational-observations", status_code=201)
def append_operational_observation(
    case_id: str,
    body: OperationalObservationInput,
    x_tenant_id: str | None = Header(default=None),
    _role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER, ROLE_MERCHANT])),
    db=Depends(get_db),
):
    """Append one governed fact and recompute only dependent advisory stages."""

    tenant_id = str(x_tenant_id or "default").strip() or "default"
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id,
        ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="shopping_case_not_found")
    try:
        return record_case_operational_observation(
            db,
            tenant_id=tenant_id,
            case_id=case_id,
            retained_purpose=case.retained_purpose or "Procurement case",
            observation=body,
        )
    except ValueError as exc:
        code = str(exc)
        status = 409 if (
            code.startswith("case_revision_conflict")
            or code == "decision_run_required_before_operational_observation"
        ) else 422
        raise HTTPException(status_code=status, detail={"code": code}) from exc


__all__ = ["router"]
