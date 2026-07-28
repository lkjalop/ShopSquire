"""Read-only operator API for governed causal supply-risk evidence."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.app.models.db import get_db
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.market_source_registry import load_market_source_registry
from src.app.services.public_market_source_fetch import fetch_public_market_source
from src.app.services.supply_risk_workbench import (
    build_supply_risk_workbench,
    list_supply_risk_scenarios,
)


router = APIRouter(prefix="/api/v1/supply-risk", tags=["supply-risk"])
_OPERATOR = [ROLE_MERCHANT, ROLE_OWNER]


class PublicSourceFetchRequest(BaseModel):
    recall_date_start: str | None = Field(default=None, max_length=32)
    recall_date_end: str | None = Field(default=None, max_length=32)
    product_name: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=120)
    series: list[str] | None = Field(default=None, max_length=5)
    signal_type: str | None = Field(default=None, max_length=80)


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


@router.get("/sources")
def public_sources(
    role: str = Depends(require_role(_OPERATOR)),
) -> dict[str, Any]:
    sources = load_market_source_registry()
    return {
        "tenant_id": current_tenant_id(),
        "sources": [
            {
                "source_id": source["source_id"],
                "publisher": source["publisher"],
                "licence_id": source["licence_id"],
                "licence_url": source["licence_url"],
                "measurement_scope": source["measurement_scope"],
                "refresh_expectation": source.get("refresh_expectation"),
                "live_fetch_supported": bool(source.get("fetch_profile")),
                "authority": source["decision_authority"],
            }
            for source in sources.values()
        ],
    }


@router.post("/sources/{source_id}/fetch")
def fetch_public_source(
    source_id: str,
    payload: PublicSourceFetchRequest,
    role: str = Depends(require_role(_OPERATOR)),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return fetch_public_market_source(
            db,
            tenant_id=current_tenant_id(),
            source_id=source_id,
            query=payload.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        detail = str(exc)
        status = 404 if detail == "external_market_source_not_registered" else 400
        raise HTTPException(status_code=status, detail=detail) from exc
