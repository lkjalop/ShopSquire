"""Authorization control-plane audit API (1.3 read surface).

Read endpoints over the four control-plane tables plus a resolver trigger. This
is the provability surface: it makes the engine's verdicts, the AI-proposed vs.
engine-disposed record, the exception queue, and retry bookkeeping inspectable.

All endpoints are defensive — if the migration has not been applied the tables
may not exist, so every query degrades to an empty result with a note rather
than a 500.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from src.app.models.db import db_session
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER

router = APIRouter(prefix="/api/v1/authz", tags=["authz-audit"])
logger = logging.getLogger("shopsquire.authz_audit")


def _rows(sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run a read query, returning a list of dicts. Empty on any failure
    (e.g. table missing before migration) — never raises."""
    try:
        from sqlalchemy import text
        with db_session() as db:
            res = db.execute(text(sql), params)
            cols = list(res.keys())
            return [dict(zip(cols, r)) for r in res.fetchall()]
    except Exception as exc:
        logger.debug("authz audit query failed: %r", exc)
        return []


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in ("[", "{"):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


@router.get("/decisions")
def list_decisions(
    action: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    clauses, params = [], {"lim": limit}
    if action:
        clauses.append("action = :action")
        params["action"] = action
    if decision:
        clauses.append("decision = :decision")
        params["decision"] = decision
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = _rows(
        f"SELECT id, trace_id, policy_version, action, requester, decision, terminal_outcome, "
        f"mode, enforced, reason, value_usd, confidence, guardrails_json, compromise_json, "
        f"residual, created_at FROM policy_evaluation_log {where} ORDER BY created_at DESC LIMIT :lim",
        params,
    )
    for r in rows:
        r["guardrails_json"] = _maybe_json(r.get("guardrails_json"))
        r["compromise_json"] = _maybe_json(r.get("compromise_json"))
    return {"count": len(rows), "decisions": rows}


@router.get("/exceptions")
def list_exceptions(
    status: Optional[str] = Query(None, description="open | resolved | retry_scheduled | governance_open"),
    limit: int = Query(100, ge=1, le=1000),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    clauses, params = [], {"lim": limit}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = _rows(
        f"SELECT id, trace_id, action, requester, terminal_outcome, reason, subject_id, "
        f"value_usd, residual, status, resolved_outcome, created_at, resolved_at "
        f"FROM exception_queue {where} ORDER BY created_at DESC LIMIT :lim",
        params,
    )
    return {"count": len(rows), "exceptions": rows}


@router.get("/interactions")
def list_interactions(
    limit: int = Query(100, ge=1, le=1000),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    rows = _rows(
        "SELECT id, trace_id, interaction_type, actor, action, proposed_json, disposed_json, "
        "subject_id, created_at FROM ai_interaction_log ORDER BY created_at DESC LIMIT :lim",
        {"lim": limit},
    )
    for r in rows:
        r["proposed_json"] = _maybe_json(r.get("proposed_json"))
        r["disposed_json"] = _maybe_json(r.get("disposed_json"))
    return {"count": len(rows), "interactions": rows}


@router.get("/policy")
def get_policy(
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """The live policy (version + per-action summary) — transparency surface."""
    try:
        from src.app.security.authorization_engine import load_policy
        policy = load_policy()
        actions = {
            name: {
                "value_cap_usd": spec.get("value_cap_usd"),
                "governance_cap_usd": spec.get("governance_cap_usd"),
                "min_confidence": spec.get("min_confidence"),
                "hard_block": bool(spec.get("hard_block")),
                "never_auto": bool(spec.get("never_auto")),
                "default_terminal": spec.get("default_terminal"),
            }
            for name, spec in (policy.get("actions") or {}).items()
        }
        return {
            "version": policy.get("version"),
            "default_mode": policy.get("default_mode"),
            "terminal_outcomes": policy.get("terminal_outcomes"),
            "actions": actions,
        }
    except Exception as exc:
        logger.debug("policy read failed: %r", exc)
        return {"error": "policy_unavailable"}


@router.post("/exceptions/resolve")
def resolve_exceptions(
    limit: int = Query(200, ge=1, le=2000),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Drive open exceptions to a terminal disposition (admin trigger; the Celery
    task does this on a schedule too)."""
    from src.app.services.exception_resolver import resolve_open_exceptions
    return {"summary": resolve_open_exceptions(limit=limit)}
