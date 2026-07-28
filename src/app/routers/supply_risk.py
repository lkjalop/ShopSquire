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
from src.app.services.supply_graph_repository import (
    approve_subject_mapping,
    bounded_dependency_paths,
    graph_quality,
    project_latest_public_fetch,
    public_source_health,
    put_edge_revision,
    put_node_revision,
)
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


class SupplyNodeRevisionRequest(BaseModel):
    logical_key: str = Field(min_length=1, max_length=250)
    node_type: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=500)
    source_system: str = Field(min_length=1, max_length=120)
    source_record_id: str = Field(min_length=1, max_length=250)
    provenance: dict[str, Any]
    valid_from: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    identity_status: str = "resolved"
    evidence_status: str = "observed"
    revision_reason: str = Field(default="initial_observation", max_length=250)
    simulation_only: bool = False


class SupplyEdgeRevisionRequest(BaseModel):
    logical_key: str = Field(min_length=1, max_length=250)
    from_node_id: str = Field(min_length=1, max_length=64)
    to_node_id: str = Field(min_length=1, max_length=64)
    relationship_type: str = Field(min_length=1, max_length=80)
    source_system: str = Field(min_length=1, max_length=120)
    source_record_id: str = Field(min_length=1, max_length=250)
    provenance: dict[str, Any]
    valid_from: str
    confidence: float = Field(ge=0.0, le=1.0)
    properties: dict[str, Any] = Field(default_factory=dict)
    evidence_status: str = "observed"
    revision_reason: str = Field(default="initial_observation", max_length=250)
    simulation_only: bool = False


class SubjectMappingRequest(BaseModel):
    external_subject_id: str = Field(min_length=1, max_length=500)
    subject_node_id: str = Field(min_length=1, max_length=64)
    mapping_basis: str = Field(min_length=1, max_length=500)
    provenance: dict[str, Any]
    valid_from: str | None = None


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


@router.post("/graph/nodes")
def revise_supply_node(
    payload: SupplyNodeRevisionRequest,
    role: str = Depends(require_role([ROLE_OWNER])),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return put_node_revision(
            db, tenant_id=current_tenant_id(), **payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/graph/edges")
def revise_supply_edge(
    payload: SupplyEdgeRevisionRequest,
    role: str = Depends(require_role([ROLE_OWNER])),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return put_edge_revision(
            db, tenant_id=current_tenant_id(), **payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/graph/paths")
def supply_paths(
    source_node_id: str = Query(min_length=1, max_length=64),
    target_node_id: str = Query(min_length=1, max_length=64),
    max_depth: int = Query(default=6, ge=1, le=8),
    role: str = Depends(require_role(_OPERATOR)),
    db=Depends(get_db),
) -> dict[str, Any]:
    return bounded_dependency_paths(
        db,
        tenant_id=current_tenant_id(),
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        max_depth=max_depth,
    )


@router.get("/graph/quality")
def supply_graph_quality(
    role: str = Depends(require_role(_OPERATOR)),
    db=Depends(get_db),
) -> dict[str, Any]:
    return graph_quality(db, tenant_id=current_tenant_id())


@router.post("/sources/{source_id}/mappings")
def approve_public_subject_mapping(
    source_id: str,
    payload: SubjectMappingRequest,
    role: str = Depends(require_role([ROLE_OWNER])),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return approve_subject_mapping(
            db,
            tenant_id=current_tenant_id(),
            source_id=source_id,
            approved_by=str(role),
            **payload.model_dump(),
        )
    except ValueError as exc:
        detail = str(exc)
        status = 404 if detail == "external_market_source_not_registered" else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/sources/{source_id}/project")
def project_public_source(
    source_id: str,
    role: str = Depends(require_role([ROLE_OWNER])),
    db=Depends(get_db),
) -> dict[str, Any]:
    return project_latest_public_fetch(
        db, tenant_id=current_tenant_id(), source_id=source_id,
    )


@router.get("/sources/{source_id}/health")
def source_health(
    source_id: str,
    role: str = Depends(require_role(_OPERATOR)),
    db=Depends(get_db),
) -> dict[str, Any]:
    return public_source_health(
        db, tenant_id=current_tenant_id(), source_id=source_id,
    )
