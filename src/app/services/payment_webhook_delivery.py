"""Durable Stripe webhook inbox and payment side-effect outbox.

The inbox separates receipt from completion. A claimed event may be retried after its
lease expires; only a processed event is a true duplicate. Side effects that cannot be
part of the order transaction (ledger/dispatch notifications) are recorded in the
outbox before the event is acknowledged.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable, Dict, Iterable, Tuple

from sqlalchemy import inspect, text

INBOX_PENDING = "pending"
INBOX_PROCESSING = "processing"
INBOX_PROCESSED = "processed"
INBOX_FAILED = "failed"

JOB_PENDING = "pending"
JOB_PROCESSING = "processing"
JOB_PROCESSED = "processed"
JOB_FAILED = "failed"


def ensure_tables(db) -> None:
    """Compatibility bootstrap for isolated tests; production uses Alembic."""
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS stripe_events ("
        "event_id TEXT PRIMARY KEY, type TEXT, payload TEXT, state TEXT NOT NULL DEFAULT 'pending', "
        "attempts INTEGER NOT NULL DEFAULT 0, claim_token TEXT, lease_expires_at REAL, "
        "last_error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT)"
    ))
    columns = {c["name"] for c in inspect(db.connection()).get_columns("stripe_events")}
    additions = {
        "payload": "TEXT",
        "state": "TEXT NOT NULL DEFAULT 'pending'",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "claim_token": "TEXT",
        "lease_expires_at": "REAL",
        "last_error": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            db.execute(text(f"ALTER TABLE stripe_events ADD COLUMN {name} {sql_type}"))
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS payment_side_effect_jobs ("
        "id TEXT PRIMARY KEY, event_id TEXT NOT NULL, job_type TEXT NOT NULL, payload TEXT NOT NULL, "
        "state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, "
        "claim_token TEXT, lease_expires_at REAL, last_error TEXT, "
        "created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "processed_at TEXT, UNIQUE(event_id, job_type))"
    ))
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_payment_side_effect_jobs_state "
        "ON payment_side_effect_jobs(state, lease_expires_at)"
    ))


def claim_event(db, *, event_id: str, event_type: str, payload: Dict[str, Any],
                lease_seconds: float = 60.0) -> Tuple[str, str | None]:
    """Return (claimed|processed|busy, claim_token). Caller commits the claim."""
    ensure_tables(db)
    now = time.time()
    token = uuid.uuid4().hex
    db.execute(text(
        "INSERT INTO stripe_events (event_id,type,payload,state,attempts,created_at,updated_at) "
        "VALUES (:i,:t,:p,'pending',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) "
        "ON CONFLICT (event_id) DO NOTHING"
    ), {"i": event_id, "t": event_type, "p": json.dumps(payload, separators=(",", ":"))})
    row = db.execute(text(
        "SELECT state, lease_expires_at FROM stripe_events WHERE event_id=:i"
    ), {"i": event_id}).fetchone()
    if not row:
        raise RuntimeError("webhook inbox row missing after insert")
    state = str(row[0] or INBOX_PENDING)
    if state == INBOX_PROCESSED:
        return "processed", None
    if state == INBOX_PROCESSING and row[1] is not None and float(row[1]) >= now:
        return "busy", None
    won = db.execute(text(
        "UPDATE stripe_events SET state='processing', claim_token=:token, "
        "lease_expires_at=:lease, attempts=attempts+1, last_error=NULL, "
        "updated_at=CURRENT_TIMESTAMP WHERE event_id=:i AND state!='processed' "
        "AND (state!='processing' OR lease_expires_at IS NULL OR lease_expires_at < :now)"
    ), {"token": token, "lease": now + lease_seconds, "i": event_id, "now": now})
    return ("claimed", token) if int(won.rowcount or 0) == 1 else ("busy", None)


def mark_event_processed(db, event_id: str, claim_token: str) -> None:
    won = db.execute(text(
        "UPDATE stripe_events SET state='processed', processed_at=CURRENT_TIMESTAMP, "
        "lease_expires_at=NULL, updated_at=CURRENT_TIMESTAMP "
        "WHERE event_id=:i AND state='processing' AND claim_token=:token"
    ), {"i": event_id, "token": claim_token})
    if int(won.rowcount or 0) != 1:
        raise RuntimeError("webhook inbox claim lost before completion")


def mark_event_failed(db, event_id: str, claim_token: str, error: str) -> None:
    db.execute(text(
        "UPDATE stripe_events SET state='failed', lease_expires_at=NULL, last_error=:e, "
        "updated_at=CURRENT_TIMESTAMP WHERE event_id=:i AND claim_token=:token"
    ), {"i": event_id, "token": claim_token, "e": str(error)[:500]})


def enqueue_job(db, *, event_id: str, job_type: str, payload: Dict[str, Any]) -> None:
    db.execute(text(
        "INSERT INTO payment_side_effect_jobs (id,event_id,job_type,payload,state,created_at,updated_at) "
        "VALUES (:id,:e,:t,:p,'pending',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) "
        "ON CONFLICT (event_id,job_type) DO NOTHING"
    ), {"id": uuid.uuid4().hex, "e": event_id, "t": job_type,
        "p": json.dumps(payload, separators=(",", ":"))})


def _claim_jobs(db, *, limit: int, lease_seconds: float) -> Iterable[Tuple[str, str, Dict[str, Any], str]]:
    ensure_tables(db)
    now = time.time()
    rows = db.execute(text(
        "SELECT id,job_type,payload FROM payment_side_effect_jobs "
        "WHERE state IN ('pending','failed') OR (state='processing' AND lease_expires_at < :now) "
        "ORDER BY created_at ASC LIMIT :lim"
    ), {"now": now, "lim": int(limit)}).fetchall()
    claimed = []
    for row in rows:
        token = uuid.uuid4().hex
        won = db.execute(text(
            "UPDATE payment_side_effect_jobs SET state='processing',claim_token=:token,"
            "lease_expires_at=:lease,attempts=attempts+1,last_error=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=:id AND (state IN ('pending','failed') OR "
            "(state='processing' AND lease_expires_at < :now))"
        ), {"token": token, "lease": now + lease_seconds, "id": str(row[0]), "now": now})
        if int(won.rowcount or 0) == 1:
            claimed.append((str(row[0]), str(row[1]), json.loads(str(row[2]) or "{}"), token))
    return claimed


def drain_jobs(db_factory: Callable[[], Any], handler: Callable[[str, Dict[str, Any]], None],
               *, limit: int = 20, lease_seconds: float = 60.0) -> Dict[str, int]:
    """Claim jobs transactionally, then execute each outside the claim transaction."""
    with db_factory() as db:
        jobs = list(_claim_jobs(db, limit=limit, lease_seconds=lease_seconds))
        db.commit()
    processed = failed = 0
    for job_id, job_type, payload, token in jobs:
        try:
            handler(job_type, payload)
            with db_factory() as db:
                db.execute(text(
                    "UPDATE payment_side_effect_jobs SET state='processed',processed_at=CURRENT_TIMESTAMP,"
                    "lease_expires_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND claim_token=:token"
                ), {"id": job_id, "token": token})
                db.commit()
            processed += 1
        except Exception as exc:
            with db_factory() as db:
                db.execute(text(
                    "UPDATE payment_side_effect_jobs SET state='failed',lease_expires_at=NULL,"
                    "last_error=:e,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND claim_token=:token"
                ), {"id": job_id, "token": token, "e": repr(exc)[:500]})
                db.commit()
            failed += 1
    return {"checked": len(jobs), "processed": processed, "failed": failed}
