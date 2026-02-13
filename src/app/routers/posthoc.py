from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

from src.app.services.posthoc_labeling import record_outcome, get_latest_outcome


router = APIRouter(prefix="/api/v1/posthoc", tags=["posthoc"])


@router.post("/record")
def record_posthoc(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    decision_id = payload.get("decision_id")
    outcome_type = payload.get("outcome_type")
    outcome_value = payload.get("outcome_value")
    if not decision_id or not outcome_type or outcome_value is None:
        raise HTTPException(status_code=400, detail="decision_id, outcome_type, outcome_value required")
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    actor_id = payload.get("actor_id")
    actor_role = payload.get("actor_role")
    playbook_run_id = payload.get("playbook_run_id")
    out_id = record_outcome(
        decision_id=str(decision_id),
        outcome_type=str(outcome_type),
        outcome_value=str(outcome_value),
        evidence=evidence,
        actor_id=str(actor_id) if actor_id else None,
        actor_role=str(actor_role) if actor_role else None,
        playbook_run_id=str(playbook_run_id) if playbook_run_id else None,
    )
    if not out_id:
        raise HTTPException(status_code=500, detail="posthoc_record_failed")
    return {"status": "ok", "id": out_id}


@router.get("/{decision_id}")
def get_posthoc(decision_id: str) -> Dict[str, Any]:
    res = get_latest_outcome(decision_id)
    if not res:
        return {"status": "not_found", "decision_id": decision_id}
    return {"status": "ok", "outcome": res}
