from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.decision_log import log_decision, log_trace_event
from src.app.services.persistence import write_audit_and_event


def _ensure_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS agent_containment (
                      id TEXT PRIMARY KEY,
                      tenant_id TEXT,
                      agent_id TEXT NOT NULL,
                      capability TEXT NOT NULL,
                      status TEXT NOT NULL,
                      score REAL,
                      reasons_json TEXT,
                      created_at INTEGER NOT NULL,
                      lifted_at INTEGER,
                      lifted_by TEXT,
                      expires_at INTEGER
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_containment_active
                    ON agent_containment(agent_id, capability, status, created_at)
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def contain_agent(
    *,
    tenant_id: str | None,
    agent_id: str,
    capability: str,
    score: float | None,
    reasons: List[str] | None,
    actor: str = "Outbound_Comms_Monitor",
    decision_id: str | None = None,
    trace_id: str | None = None,
    ttl_seconds: int | None = None,
) -> Dict[str, Any]:
    """Apply containment to an agent/capability. Idempotent-ish (multiple rows allowed, but is_contained checks latest)."""
    _ensure_table()
    now = int(time.time())
    cid = f"ac-{uuid.uuid4().hex}"
    exp = None
    if ttl_seconds is not None:
        try:
            exp = int(now + max(60, int(ttl_seconds)))
        except Exception:
            exp = None

    # Ensure we have a decision_id for audit-grade evidence.
    dec_id = decision_id
    if not dec_id:
        try:
            dec_id = log_decision(
                agent_name="agent_containment",
                tenant_id=tenant_id,
                input_data={"agent_id": agent_id, "capability": capability},
                retrieved_context={"reasons": reasons or [], "score": score},
                proposed_action={"status": "contained", "capability": capability, "expires_at": exp},
                agent_reasoning="automatic_containment_on_outbound_anomaly",
                policy_version="agent_containment_v1",
                approval_required=False,
                execution_status="executed",
                event_type="agent_containment",
            )
        except Exception:
            dec_id = None

    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO agent_containment
                    (id, tenant_id, agent_id, capability, status, score, reasons_json, created_at, expires_at)
                    VALUES
                    (:id, :tenant_id, :agent_id, :capability, :status, :score, :reasons_json, :created_at, :expires_at)
                    """
                ),
                {
                    "id": cid,
                    "tenant_id": tenant_id,
                    "agent_id": str(agent_id),
                    "capability": str(capability),
                    "status": "contained",
                    "score": float(score) if score is not None else None,
                    "reasons_json": json.dumps(reasons or [], ensure_ascii=False),
                    "created_at": now,
                    "expires_at": exp,
                },
            )
            db.commit()
    except Exception:
        pass

    # Decision audit chain
    try:
        if dec_id:
            write_audit_and_event(
                decision_id=str(dec_id),
                action="agent_containment_applied",
                actor=actor,
                metadata={
                    "agent_id": agent_id,
                    "capability": capability,
                    "score": score,
                    "reasons": reasons or [],
                    "expires_at": exp,
                    "containment_id": cid,
                },
            )
    except Exception:
        pass

    # Trace event
    try:
        tid = trace_id or dec_id
        if tid:
            log_trace_event(
                trace_id=str(tid),
                event_type="agent_containment",
                source_type="agent",
                source_id=actor,
                target_type="agent",
                target_id=str(agent_id),
                payload={
                    "containment_id": cid,
                    "tenant_id": tenant_id,
                    "capability": capability,
                    "status": "contained",
                    "score": score,
                    "reasons": reasons or [],
                    "expires_at": exp,
                },
            )
    except Exception:
        pass

    return {"ok": True, "containment_id": cid, "decision_id": dec_id, "capability": capability, "agent_id": agent_id, "expires_at": exp}


def is_contained(*, agent_id: str, capability: str) -> bool:
    _ensure_table()
    now = int(time.time())
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT status, expires_at
                    FROM agent_containment
                    WHERE agent_id = :agent_id AND capability = :capability
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"agent_id": str(agent_id), "capability": str(capability)},
            ).fetchone()
        if not row:
            return False
        status = str(row[0] or "").lower()
        exp = row[1]
        if exp is not None:
            try:
                if int(exp) <= now:
                    return False
            except Exception:
                pass
        return status == "contained"
    except Exception:
        return False


def lift_containment(
    *,
    agent_id: str,
    capability: str,
    actor: str,
    decision_id: str | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    _ensure_table()
    now = int(time.time())
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    UPDATE agent_containment
                    SET status = 'lifted', lifted_at = :now, lifted_by = :actor
                    WHERE agent_id = :agent_id AND capability = :capability AND status = 'contained'
                    """
                ),
                {"now": now, "actor": actor, "agent_id": str(agent_id), "capability": str(capability)},
            )
            db.commit()
    except Exception:
        pass
    try:
        if decision_id:
            write_audit_and_event(
                decision_id=str(decision_id),
                action="agent_containment_lifted",
                actor=actor,
                metadata={"agent_id": agent_id, "capability": capability},
            )
    except Exception:
        pass
    try:
        tid = trace_id or decision_id
        if tid:
            log_trace_event(
                trace_id=str(tid),
                event_type="agent_containment_lifted",
                source_type="admin",
                source_id=actor,
                target_type="agent",
                target_id=str(agent_id),
                payload={"capability": capability, "status": "lifted"},
            )
    except Exception:
        pass
    return {"ok": True, "agent_id": agent_id, "capability": capability, "status": "lifted"}


def list_containments(*, limit: int = 100, status: str | None = None) -> List[Dict[str, Any]]:
    _ensure_table()
    limit = max(1, min(int(limit or 100), 500))
    where = ""
    params: Dict[str, Any] = {"limit": limit}
    if status:
        where = "WHERE status = :status"
        params["status"] = str(status)
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    f"""
                    SELECT id, tenant_id, agent_id, capability, status, score, reasons_json, created_at, expires_at, lifted_at, lifted_by
                    FROM agent_containment
                    {where}
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows or []:
            try:
                reasons = json.loads(r[6]) if r[6] else []
            except Exception:
                reasons = []
            out.append(
                {
                    "id": r[0],
                    "tenant_id": r[1],
                    "agent_id": r[2],
                    "capability": r[3],
                    "status": r[4],
                    "score": float(r[5] or 0.0) if r[5] is not None else None,
                    "reasons": reasons,
                    "created_at": int(r[7] or 0),
                    "expires_at": int(r[8]) if r[8] is not None else None,
                    "lifted_at": int(r[9]) if r[9] is not None else None,
                    "lifted_by": r[10],
                }
            )
        return out
    except Exception:
        return []

