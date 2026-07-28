"""Read-only operator API for governed causal supply-risk evidence."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.supply_risk_workbench import (
    build_supply_risk_workbench,
    list_supply_risk_scenarios,
)


router = APIRouter(prefix="/api/v1/supply-risk", tags=["supply-risk"])
_OPERATOR = [ROLE_MERCHANT, ROLE_OWNER]


@router.get("/scenarios")
def scenarios(
    role: str = Depends(require_role(_OPERATOR)),
) -> dict[str, Any]:
    return {
        "tenant_id": current_tenant_id(),
        "scenarios": list_supply_risk_scenarios(),
        "authority": "simulation_only",
    }


@router.get("/workbench/{scenario_id}")
def workbench(
    scenario_id: str,
    seed: int = Query(42, ge=0, le=2_147_483_647),
    days: int = Query(400, ge=60, le=1095),
    role: str = Depends(require_role(_OPERATOR)),
) -> dict[str, Any]:
    try:
        return build_supply_risk_workbench(
            tenant_id=current_tenant_id(),
            scenario_id=scenario_id,
            seed=seed,
            days=days,
        )
    except ValueError as exc:
        if str(exc) == "synthetic_supply_scenario_not_found":
            raise HTTPException(
                status_code=404,
                detail="supply_risk_scenario_not_found",
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
