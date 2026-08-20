"""Explicitly enabled, read-only procurement disturbance certification surface."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.conversational_procurement_certificate import (
    TURN_ONE,
    TURN_TWO,
    build_conversational_procurement_certificate,
)
from src.app.services.procurement_scenario_harness import (
    ProcurementScenario,
    run_procurement_scenario,
)

router = APIRouter(prefix="/api/v1/certification/procurement", tags=["certification"])


class DisturbanceCertificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: ProcurementScenario
    knowledge_cutoff: datetime
    evaluation_time: datetime


class ConversationalCertificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_one: str = TURN_ONE
    turn_two: str = TURN_TWO
    interpretation_instant: datetime = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _enabled() -> bool:
    return str(os.getenv("PORTFOLIO_CERTIFICATION_ENABLED") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


@router.post("/disturbances/evaluate")
def evaluate_disturbance_certificate(
    request: DisturbanceCertificationRequest,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> dict[str, Any]:
    if not _enabled():
        raise HTTPException(status_code=404, detail="portfolio_certification_disabled")
    if request.knowledge_cutoff.tzinfo is None or request.evaluation_time.tzinfo is None:
        raise HTTPException(status_code=422, detail="certification_cutoffs_require_timezone")
    result = run_procurement_scenario(
        request.scenario,
        knowledge_cutoff=request.knowledge_cutoff,
        evaluation_time=request.evaluation_time,
    )
    artifact = {
        "schema_version": "procurement-disturbance-certificate-v1",
        "tenant_id": current_tenant_id(),
        "scenario": request.scenario.model_dump(mode="json"),
        "knowledge_cutoff": request.knowledge_cutoff.isoformat(),
        "evaluation_time": request.evaluation_time.isoformat(),
        "result": result.model_dump(mode="json"),
        "provider_accounting": {
            "external_calls": sum(row.external_calls for row in result.projections),
            "rfq_calls": sum(row.rfq_calls for row in result.projections),
            "cart_mutations": sum(row.cart_mutations for row in result.projections),
            "paid_calls": 0,
        },
        "authority": "deterministic_certification_only",
        "commercial_authority_granted": False,
    }
    encoded = json.dumps(
        artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    artifact["artifact_sha256"] = hashlib.sha256(encoded).hexdigest()
    return artifact


@router.post("/conversational-spatiotemporal/evaluate")
def evaluate_conversational_certificate(
    request: ConversationalCertificationRequest,
    _role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER, ROLE_MERCHANT])),
) -> dict[str, Any]:
    if not _enabled():
        raise HTTPException(status_code=404, detail="portfolio_certification_disabled")
    if request.interpretation_instant.tzinfo is None:
        raise HTTPException(status_code=422, detail="certification_cutoffs_require_timezone")
    return build_conversational_procurement_certificate(
        turn_one=request.turn_one,
        turn_two=request.turn_two,
        interpretation_instant=request.interpretation_instant,
    )


__all__ = ["router"]
