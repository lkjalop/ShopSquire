from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException

from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, require_role
from src.app.services.decision_replay import build_causal_graph, replay_decision


router = APIRouter(prefix="/api/v1/decisions", tags=["decision-replay"])


@router.get("/replay/{decision_id}")
def replay(decision_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    out = replay_decision(decision_id)
    if not out.get("available"):
        raise HTTPException(status_code=404, detail="decision_not_found")
    return out


@router.get("/trace/{trace_id}/causal")
def causal(trace_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    return build_causal_graph(trace_id)
