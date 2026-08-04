"""Read-only operator API for governed causal supply-risk evidence."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.app.models.db import get_db
from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import (
    ROLE_MERCHANT,
    ROLE_OWNER,
    OperatorSubject,
    operator_subject,
    require_role,
)
from src.app.services.market_source_registry import load_market_source_registry
from src.app.services.disruption_intelligence import (
    project_disruption_impact,
    record_disruption_observation,
)
from src.app.services.public_market_source_fetch import fetch_public_market_source
from src.app.services.qualified_alternative_workflow import (
    propose_qualified_alternatives,
)
from src.app.services.supply_graph_repository import (
    approve_subject_mapping,
    bounded_dependency_paths,
    graph_quality,
    project_latest_public_fetch,
    public_source_health,
    put_edge_revision,
    put_node_revision,
)
from src.app.services.supply_exposure_manifest import import_supply_exposure_manifest
from src.app.services.synthetic_causal_evaluation import evaluate_scenario_cohorts
from src.app.services.supply_hypothesis_workflow import (
    create_grounded_hypothesis,
    get_grounded_hypothesis,
    record_supplier_hypothesis_observation,
    reevaluate_grounded_hypothesis,
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
    commodities: list[str] | None = Field(default=None, max_length=5)
    statistics: list[str] | None = Field(default=None, max_length=5)
    countries: list[str] | None = Field(default=None, max_length=10)
    latest_year_only: bool = True
    point: str | None = Field(default=None, max_length=32)
    area: str | None = Field(default=None, max_length=2)
    zone: str | None = Field(default=None, max_length=8)


class DisruptionObservationRequest(BaseModel):
    disruption_type: str = Field(min_length=1, max_length=80)
    affected_node_ids: list[str] = Field(min_length=1, max_length=50)
    geography: str | None = Field(default=None, max_length=120)
    effective_from: str
    effective_to: str | None = None
    observed_at: str
    retrieved_at: str
    published_at: str | None = None
    fresh_until: str
    source_id: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=250)
    source_revision: str = Field(min_length=1, max_length=160)
    source_licence: str = Field(min_length=1, max_length=250)
    evidence_ref: str = Field(min_length=1, max_length=500)
    severity: str = Field(min_length=1, max_length=32)
    probability_range: tuple[float, float]
    delay_range_days: tuple[int, int]
    cost_impact_range_minor: tuple[int, int]
    currency: str = Field(min_length=3, max_length=3)
    claim_status: str = Field(min_length=1, max_length=32)
    contradiction_status: str = Field(default="unchallenged", max_length=40)
    contradiction_group: str | None = Field(default=None, max_length=250)


class DisruptionProjectionRequest(BaseModel):
    target_node_id: str = Field(min_length=1, max_length=64)
    baseline_version: str = Field(min_length=1, max_length=160)
    baseline: dict[str, Any]
    decision_time: str


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


class SupplyExposureManifestRequest(BaseModel):
    schema_version: str = Field(min_length=1, max_length=50)
    source_system: str = Field(min_length=1, max_length=120)
    snapshot_id: str = Field(min_length=1, max_length=250)
    revision: int = Field(ge=1)
    observed_at: str
    valid_from: str | None = None
    fresh_until: str
    provenance: dict[str, Any]
    nodes: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    edges: list[dict[str, Any]] = Field(default_factory=list, max_length=2_000)


class CausalEvaluationRequest(BaseModel):
    scenario_ids: list[str] = Field(min_length=1, max_length=12)
    seeds: list[int] = Field(min_length=1, max_length=8)
    days: int = Field(default=400, ge=60, le=1095)
    cohort_dimensions: dict[str, dict[str, str]] = Field(default_factory=dict)
    include_adversarial: bool = True


class GroundedHypothesisRequest(BaseModel):
    target_node_id: str = Field(min_length=1, max_length=64)
    decision_time: str
    case_id: str | None = Field(default=None, max_length=160)
    known_exposure: dict[str, Any] = Field(default_factory=dict)


class SupplierHypothesisObservationRequest(BaseModel):
    observation_type: str = Field(min_length=1, max_length=32)
    supplier_ref: str = Field(min_length=1, max_length=250)
    source_message_id: str = Field(min_length=1, max_length=500)
    observation: dict[str, Any]
    provenance: dict[str, Any]
    observed_at: str


class HypothesisReevaluationRequest(BaseModel):
    decision_time: str


class QualifiedAlternativeRequest(BaseModel):
    target_currency: str = Field(min_length=3, max_length=3)
    target_uom: str = Field(min_length=1, max_length=40)
    quotes: list[dict[str, Any]] = Field(min_length=1, max_length=100)


def _actor(role: str, subject: OperatorSubject) -> str:
    return (subject.user_id or "").strip() or f"key:{role}"


def _workflow_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status = 404 if detail in {
        "supply_target_not_in_tenant_graph",
        "supply_hypothesis_not_in_tenant",
    } else 400
    return HTTPException(status_code=status, detail=detail)


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


@router.post("/evaluation/cohorts")
def evaluate_causal_cohorts(
    payload: CausalEvaluationRequest,
    role: str = Depends(require_role(_OPERATOR)),
) -> dict[str, Any]:
    _ = role
    try:
        return evaluate_scenario_cohorts(**payload.model_dump())
    except ValueError as exc:
        detail = str(exc)
        status = 404 if detail == "synthetic_supply_scenario_not_found" else 400
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/hypotheses")
def create_supply_hypothesis(
    payload: GroundedHypothesisRequest,
    role: str = Depends(require_role(_OPERATOR)),
    subject: OperatorSubject = Depends(operator_subject),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_grounded_hypothesis(
            db,
            tenant_id=current_tenant_id(),
            created_by=_actor(role, subject),
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise _workflow_error(exc) from exc


@router.get("/hypotheses/{hypothesis_id}")
def grounded_supply_hypothesis(
    hypothesis_id: str,
    role: str = Depends(require_role(_OPERATOR)),
    db=Depends(get_db),
) -> dict[str, Any]:
    _ = role
    try:
        return get_grounded_hypothesis(
            db,
            tenant_id=current_tenant_id(),
            hypothesis_id=hypothesis_id,
        )
    except ValueError as exc:
        raise _workflow_error(exc) from exc


@router.post("/hypotheses/{hypothesis_id}/supplier-observations")
def supplier_hypothesis_observation(
    hypothesis_id: str,
    payload: SupplierHypothesisObservationRequest,
    role: str = Depends(require_role(_OPERATOR)),
    subject: OperatorSubject = Depends(operator_subject),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return record_supplier_hypothesis_observation(
            db,
            tenant_id=current_tenant_id(),
            hypothesis_id=hypothesis_id,
            recorded_by=_actor(role, subject),
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise _workflow_error(exc) from exc


@router.post("/hypotheses/{hypothesis_id}/reevaluate")
def reevaluate_supply_hypothesis(
    hypothesis_id: str,
    payload: HypothesisReevaluationRequest,
    role: str = Depends(require_role(_OPERATOR)),
    subject: OperatorSubject = Depends(operator_subject),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return reevaluate_grounded_hypothesis(
            db,
            tenant_id=current_tenant_id(),
            hypothesis_id=hypothesis_id,
            decision_time=payload.decision_time,
            created_by=_actor(role, subject),
        )
    except ValueError as exc:
        raise _workflow_error(exc) from exc


@router.post("/hypotheses/{hypothesis_id}/qualified-alternatives")
def qualified_alternative_proposal(
    hypothesis_id: str,
    payload: QualifiedAlternativeRequest,
    role: str = Depends(require_role(_OPERATOR)),
    subject: OperatorSubject = Depends(operator_subject),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return propose_qualified_alternatives(
            db,
            tenant_id=current_tenant_id(),
            hypothesis_id=hypothesis_id,
            created_by=_actor(role, subject),
            **payload.model_dump(),
        )
    except ValueError as exc:
        raise _workflow_error(exc) from exc


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


@router.post("/disruptions")
def create_disruption_observation(
    payload: DisruptionObservationRequest,
    role: str = Depends(require_role([ROLE_OWNER])),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        result = record_disruption_observation(
            db, tenant_id=current_tenant_id(), **payload.model_dump(),
        )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/disruptions/{observation_id}/project")
def create_disruption_projection(
    observation_id: str,
    payload: DisruptionProjectionRequest,
    role: str = Depends(require_role([ROLE_OWNER])),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        result = project_disruption_impact(
            db, tenant_id=current_tenant_id(), observation_id=observation_id,
            **payload.model_dump(),
        )
        db.commit()
        return result
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/graph/exposure-manifests")
def import_supply_exposure(
    payload: SupplyExposureManifestRequest,
    role: str = Depends(require_role([ROLE_OWNER])),
    subject: OperatorSubject = Depends(operator_subject),
    db=Depends(get_db),
) -> dict[str, Any]:
    try:
        return import_supply_exposure_manifest(
            db,
            tenant_id=current_tenant_id(),
            manifest=payload.model_dump(exclude_none=True),
            approved_by=_actor(role, subject),
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
