"""Durable retry queue for internal supplier-RFQ drafting.

Drafting never sends to a supplier. A failed auto-draft remains at GATE 1 and is retried by a
bounded worker; the buyer/operator can see that the draft is pending rather than being told it
succeeded or receiving a silent COMMITTED case.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

_DDL = """
CREATE TABLE IF NOT EXISTS fulfillment_draft_retry (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    item_ref TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    trace_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(case_id, item_ref, quantity)
)
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_table(db) -> None:
    dialect = str(getattr(getattr(db, "bind", None), "dialect", None).name
                  if getattr(getattr(db, "bind", None), "dialect", None) else "")
    app_env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    # SQLite/local retains self-bootstrap for the portable demo database. Staging/production
    # must be migration-owned; a missing table then fails loudly instead of mutating schema at
    # request time and concealing a broken deployment.
    if dialect != "sqlite" and app_env not in ("local", "dev", "development", "test"):
        return
    db.execute(text(_DDL))
    db.execute(text("CREATE INDEX IF NOT EXISTS ix_fulfillment_draft_retry_due "
                    "ON fulfillment_draft_retry(status, next_attempt_at)"))


def enqueue(db, *, case_id: str, item_ref: str, quantity: int,
            trace_id: Optional[str], error: BaseException) -> Dict[str, Any]:
    ensure_table(db)
    now = _now().isoformat()
    payload = {"id": str(uuid.uuid4()), "case": case_id, "item": item_ref,
               "qty": int(quantity), "trace": trace_id, "now": now,
               "error": f"{type(error).__name__}: {str(error)[:500]}"}
    db.execute(text(
        "INSERT INTO fulfillment_draft_retry "
        "(id,case_id,item_ref,quantity,trace_id,status,attempt_count,next_attempt_at,last_error,created_at,updated_at) "
        "VALUES (:id,:case,:item,:qty,:trace,'pending',0,:now,:error,:now,:now) "
        "ON CONFLICT(case_id,item_ref,quantity) DO UPDATE SET "
        "status='pending', next_attempt_at=:now, last_error=:error, updated_at=:now"
    ), payload)
    return {"status": "pending_retry", "attempt_count": 0, "last_error": payload["error"]}


def status_for_case(db, case_id: str) -> Optional[Dict[str, Any]]:
    ensure_table(db)
    row = db.execute(text(
        "SELECT status,attempt_count,next_attempt_at,last_error,updated_at "
        "FROM fulfillment_draft_retry WHERE case_id=:case ORDER BY updated_at DESC LIMIT 1"
    ), {"case": case_id}).mappings().first()
    return dict(row) if row else None


def run_due(db, *, limit: int = 20, max_attempts: int = 5) -> Dict[str, int]:
    """Claim and retry due rows. Safe for concurrent PostgreSQL workers via SKIP LOCKED."""
    ensure_table(db)
    now = _now()
    dialect = str(getattr(getattr(db, "bind", None), "dialect", None).name if getattr(getattr(db, "bind", None), "dialect", None) else "")
    lock = " FOR UPDATE SKIP LOCKED" if dialect == "postgresql" else ""
    rows = db.execute(text(
        "SELECT id,case_id,item_ref,quantity,trace_id,attempt_count FROM fulfillment_draft_retry "
        "WHERE status IN ('pending','retrying') AND next_attempt_at<=:now "
        "ORDER BY next_attempt_at LIMIT :limit" + lock
    ), {"now": now.isoformat(), "limit": max(1, min(int(limit), 100))}).mappings().all()
    out = {"claimed": 0, "succeeded": 0, "failed": 0, "dead": 0}
    from src.app.services.fulfillment import draft as fdraft
    from src.app.services.fulfillment.domain import Actor, ActorType
    actor = Actor(ActorType.AGENT, "Procurement_Agent")
    for row in rows:
        attempts = int(row["attempt_count"] or 0) + 1
        claimed = db.execute(text(
            "UPDATE fulfillment_draft_retry SET status='retrying',attempt_count=:attempts,updated_at=:now "
            "WHERE id=:id AND attempt_count=:prior AND status IN ('pending','retrying')"
        ), {"attempts": attempts, "now": now.isoformat(), "id": row["id"],
            "prior": int(row["attempt_count"] or 0)}).rowcount
        if not claimed:
            continue
        out["claimed"] += 1
        try:
            with db.begin_nested():
                result, _draft = fdraft.draft_and_record(
                    db, case_id=row["case_id"], actor=actor, item_ref=row["item_ref"],
                    quantity=int(row["quantity"]), estimated_value_cents=0,
                    trace_id=row["trace_id"])
                if not result.ok:
                    raise RuntimeError(result.reason or "draft_transition_failed")
            db.execute(text("UPDATE fulfillment_draft_retry SET status='succeeded',last_error=NULL,updated_at=:now WHERE id=:id"),
                       {"now": _now().isoformat(), "id": row["id"]})
            out["succeeded"] += 1
        except Exception as exc:
            dead = attempts >= max_attempts
            delay = min(3600, 30 * (2 ** max(0, attempts - 1)))
            db.execute(text(
                "UPDATE fulfillment_draft_retry SET status=:status,next_attempt_at=:next,last_error=:error,updated_at=:now WHERE id=:id"
            ), {"status": "dead" if dead else "pending",
                "next": (now + timedelta(seconds=delay)).isoformat(),
                "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                "now": _now().isoformat(), "id": row["id"]})
            out["dead" if dead else "failed"] += 1
    return out
