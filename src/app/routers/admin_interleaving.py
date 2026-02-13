from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends
import json

from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER
from src.app.models.db import db_session


router = APIRouter(prefix="/api/v1/admin/interleaving", tags=["admin", "interleaving"])


def _safe_load(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return {}
    return payload or {}


@router.get("/{trace_id}/summary")
def interleaving_summary(trace_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))):
    """Summarize interleaving events and tool budgets for a trace.

    Returns compact stats: tier decision, tool budget remaining (last),
    interleaving iterations, agent invocation count + total latency, and tags.
    """
    try:
        with db_session() as db:
            rows = db.execute(
                "SELECT event_type, payload FROM decision_trace_events WHERE trace_id = :tid",
                {"tid": trace_id},
            ).fetchall()
    except Exception:
        raise HTTPException(status_code=500, detail="fetch_failed")

    stats: Dict[str, Any] = {
        "trace_id": trace_id,
        "tier": None,
        "tool_budget_remaining": None,
        "interleaving_iterations": 0,
        "interleaving_summary": {},
        "agent_invocations": 0,
        "agent_latency_ms_total": 0,
        "tags": [],
    }

    tags_set = set()
    for (evt_type, raw_payload) in rows or []:
        payload = _safe_load(raw_payload)
        if evt_type == "tier_decision":
            t = payload.get("tier")
            try:
                stats["tier"] = int(t) if t is not None else stats["tier"]
            except Exception:
                stats["tier"] = stats["tier"] or t
        elif evt_type == "tool_budget":
            rem = payload.get("remaining")
            try:
                stats["tool_budget_remaining"] = int(rem)
            except Exception:
                stats["tool_budget_remaining"] = rem
        elif evt_type == "interleaving_event":
            stats["interleaving_iterations"] += 1
            # accumulate lightweight tags
            if isinstance(payload, dict):
                for k in ("event", "tool_name", "reason"):
                    v = payload.get(k)
                    if v:
                        try:
                            tags_set.add(str(v)[:24])
                        except Exception:
                            pass
        elif evt_type == "interleaving_summary":
            if isinstance(payload, dict):
                stats["interleaving_summary"] = payload
        elif evt_type in ("agent_invocation", "model_invoke"):
            stats["agent_invocations"] += 1
            try:
                v = payload.get("latency_ms")
                if isinstance(v, (int, float)):
                    stats["agent_latency_ms_total"] += int(v)
                elif v is not None:
                    stats["agent_latency_ms_total"] += int(float(str(v)))
            except Exception:
                pass
            try:
                tags = payload.get("tags")
                if isinstance(tags, list):
                    for t in tags[:12]:
                        tags_set.add(str(t))
            except Exception:
                pass

    stats["tags"] = sorted(list(tags_set))
    return {"summary": stats}
