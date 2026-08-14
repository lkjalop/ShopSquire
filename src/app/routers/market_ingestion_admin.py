"""Tenant-scoped operator visibility and explicit connector dead-letter replay."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.models.db import get_db
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.market_ingestion_observability import (
    connector_health, list_dead_letters, replay_dead_letter,
)


router = APIRouter(prefix="/api/v1/admin/market-ingestion", tags=["admin", "market-ingestion"])


@router.get("/health")
def market_ingestion_health(
    window: int = Query(20, ge=1, le=100), db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
):
    _ = role
    return connector_health(db, tenant_id=str(current_tenant_id() or "default"), window=window)


@router.get("/dead-letters")
def market_ingestion_dead_letters(
    status: str = Query("pending", pattern="^(pending|resolved)$"),
    limit: int = Query(100, ge=1, le=500), db=Depends(get_db),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    _ = role
    return {"dead_letters": list_dead_letters(
        db, tenant_id=str(current_tenant_id() or "default"), status=status, limit=limit,
    ), "authority": "operator_observability_only"}


@router.post("/dead-letters/{dead_letter_id}/replay")
def replay_market_ingestion_dead_letter(
    dead_letter_id: str, db=Depends(get_db),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    _ = role
    result = replay_dead_letter(
        db, tenant_id=str(current_tenant_id() or "default"), dead_letter_id=dead_letter_id,
    )
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="dead_letter_not_found")
    if result["status"] in {"incompatible_source_schema", "policy_rejection_requires_correction"}:
        raise HTTPException(status_code=409, detail=result)
    db.commit()
    return result
