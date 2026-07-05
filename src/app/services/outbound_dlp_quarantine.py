"""Outbound-DLP quarantine + human-release queue (agnostic CORE).

The outbound content DLP hard-blocks a secret-bearing send. But a scan can false-positive (a signed
contract hash, a licence key the SUPPLIER legitimately needs) — a hard block with no release path
turns a safe control into a workflow dead-end. This parks a blocked send and lets a HUMAN OWNER
review + release it (GATE-2 mold): the release is the second-person judgement that the flagged
content is intended, recorded with the actor.

Stores subject+body (that IS the quarantined-for-review payload — access is owner-only at the
router). Append-only status transitions: pending_release → released | discarded. Best-effort;
never raises into the send path. Vertical-blind.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

_DDL = """
CREATE TABLE IF NOT EXISTS outbound_dlp_quarantine (
    id TEXT PRIMARY KEY,
    tenant_id TEXT,
    agent_id TEXT,
    to_addr TEXT,
    subject TEXT,
    body TEXT,
    dlp_json TEXT,
    status TEXT DEFAULT 'pending_release',
    released_by TEXT,
    released_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def _ensure(db) -> None:
    db.execute(text(_DDL))


def quarantine_blocked_send(*, tenant_id: Optional[str], agent_id: str, to: str, subject: str,
                            body: str, dlp: Dict[str, Any]) -> Optional[str]:
    """Park a DLP-blocked send for human review. Returns the quarantine id, or None. Never raises."""
    try:
        from src.app.models.db import db_session
        qid = f"dlpq-{uuid.uuid4().hex[:12]}"
        with db_session() as db:
            _ensure(db)
            db.execute(text(
                "INSERT INTO outbound_dlp_quarantine (id, tenant_id, agent_id, to_addr, subject, body, "
                "dlp_json, status) VALUES (:i,:t,:a,:to,:s,:b,:d,'pending_release')"),
                {"i": qid, "t": tenant_id, "a": str(agent_id or ""), "to": str(to or ""),
                 "s": str(subject or ""), "b": str(body or ""),
                 "d": json.dumps(dlp or {}, ensure_ascii=False)})
            db.commit()
        return qid
    except Exception:
        return None


def _row_to_summary(r, *, include_body: bool = False) -> Dict[str, Any]:
    out = {"id": r[0], "tenant_id": r[1], "agent_id": r[2], "to_addr": r[3], "subject": r[4],
           "status": r[7], "released_by": r[8], "released_at": r[9], "created_at": r[10]}
    try:
        out["dlp"] = json.loads(r[6]) if r[6] else {}
    except Exception:
        out["dlp"] = {}
    if include_body:
        out["body"] = r[5]
    return out


def list_quarantine(db, *, status: str = "pending_release", tenant_id: Optional[str] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
    """Quarantined sends (default the pending queue). Body is NOT included — the list is a review
    index; the body (which holds the flagged secret) is fetched only on explicit inspect/release."""
    try:
        _ensure(db)
        sql = "SELECT id,tenant_id,agent_id,to_addr,subject,body,dlp_json,status,released_by,released_at,created_at FROM outbound_dlp_quarantine WHERE status=:st "
        params: Dict[str, Any] = {"st": status, "lim": int(limit)}
        if tenant_id is not None:
            sql += "AND COALESCE(tenant_id,'')=:t "
            params["t"] = str(tenant_id)
        rows = db.execute(text(sql + "ORDER BY created_at DESC LIMIT :lim"), params).fetchall()
    except Exception:
        return []
    return [_row_to_summary(r) for r in rows]


def get_quarantined(db, qid: str) -> Optional[Dict[str, Any]]:
    """Fetch one quarantined send WITH the body (owner-only inspect / release execution)."""
    try:
        _ensure(db)
        r = db.execute(text("SELECT id,tenant_id,agent_id,to_addr,subject,body,dlp_json,status,released_by,released_at,created_at "
                            "FROM outbound_dlp_quarantine WHERE id=:i LIMIT 1"), {"i": qid}).fetchone()
    except Exception:
        return None
    return _row_to_summary(r, include_body=True) if r else None


def mark_status(db, qid: str, *, status: str, actor: str) -> bool:
    """Transition a pending item to released/discarded. Idempotent guard: only from pending_release."""
    try:
        _ensure(db)
        res = db.execute(text(
            "UPDATE outbound_dlp_quarantine SET status=:st, released_by=:by, released_at=CURRENT_TIMESTAMP "
            "WHERE id=:i AND status='pending_release'"),
            {"st": status, "by": str(actor or ""), "i": qid})
        db.commit()
        return bool(getattr(res, "rowcount", 0))
    except Exception:
        return False
