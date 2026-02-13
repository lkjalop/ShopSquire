from __future__ import annotations

from fastapi import APIRouter, Depends

from src.app.data_readiness.report import compute_inventory_readiness
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_OWNER, ROLE_MERCHANT

router = APIRouter(prefix="/api/v1/data", tags=["data"])


@router.get("/readiness")
def get_readiness(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    rep = compute_inventory_readiness()
    return {"inventory": {"score": rep.score, "level": rep.level, "checks": rep.checks, "summary": rep.summary}}

