"""Reliable outbound supplier-message queue (agnostic CORE) — durable send with retry + backoff +
dead-letter + idempotency + 855-acknowledgement tracking.

A supplier RFQ/PO send must not be fire-and-forget: at scale you need at-least-once delivery with bounded
retries, a dead-letter for messages that never succeed, idempotency so a retried command never double-sends,
and tracking of the supplier's acknowledgement (EDI 855). This is that queue. The actual transmission goes
through the INJECTED transport seam (SANDBOX by default; SMTP at deploy) — no secrets here. Ready to carry a
real send the moment SMTP creds land; until then it durably records + 'sends' via sandbox.

Vertical-blind: recipient/subject/body are opaque strings; status/attempts are counts. Best-effort; never
raises into the workflow.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.outbound_queue")

_DDL = """
CREATE TABLE IF NOT EXISTS outbound_message (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT,
    case_id          TEXT,
    recipient        TEXT,
    subject          TEXT,
    body             TEXT,
    idempotency_key  TEXT,
    status           TEXT DEFAULT 'pending',   -- pending | sending | sent | dead_letter
    attempts         INTEGER DEFAULT 0,
    max_attempts     INTEGER DEFAULT 5,
    next_attempt_at  TEXT,
    provider_ref     TEXT,
    ack_status       TEXT DEFAULT 'awaiting',  -- awaiting | acked  (EDI 855)
    acked_at         TEXT,
    last_error       TEXT,
    actor_type       TEXT,                     -- the approved transition intent, replayed on deferred delivery
    actor_id         TEXT,
    transition_event TEXT,
    created_at       TEXT,
    updated_at       TEXT,
    UNIQUE (tenant_id, idempotency_key)
)
"""

# How long a row may sit CLAIMED ('sending') before a crashed worker's claim is reclaimed for retry.
def _stale_claim_seconds() -> int:
    return int(os.getenv("OUTBOUND_STALE_CLAIM_SEC", "300") or 300)


def _now_iso(now_iso: Optional[str]) -> str:
    """Canonical 'T'-separated, seconds-precision ISO. ALL queue timestamps go through here so the lexical
    next_attempt_at <= now comparison is sound — callers pass space- OR T-separated strings (the workflow uses
    a space, ISO uses a 'T'); mixing them silently breaks string ordering ('T' 0x54 > ' ' 0x20)."""
    from datetime import datetime, timezone
    if now_iso:
        try:
            return datetime.fromisoformat(str(now_iso)).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            return str(now_iso)
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _plus_seconds(now_iso: str, seconds: int) -> str:
    from datetime import datetime, timedelta
    try:
        base = datetime.fromisoformat(str(now_iso))
    except Exception:
        from datetime import timezone
        base = datetime.now(timezone.utc).replace(tzinfo=None)
    return (base + timedelta(seconds=int(seconds))).isoformat(timespec="seconds")


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff: base * 2^attempts, capped. attempts is the count AFTER this failure."""
    base = int(os.getenv("OUTBOUND_RETRY_BASE_SEC", "60") or 60)
    cap = int(os.getenv("OUTBOUND_RETRY_CAP_SEC", "3600") or 3600)
    return min(cap, base * (2 ** max(0, int(attempts) - 1)))


def enqueue(db, *, case_id: str, recipient: str, subject: str, body: str, idempotency_key: str,
            max_attempts: int = 5, tenant_id: str = "default", actor_type: str = "", actor_id: str = "",
            transition_event: str = "", now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Durably enqueue an outbound supplier message. IDEMPOTENT on (tenant, idempotency_key) — a retried
    enqueue of the same content_hash returns the existing row (deduped), never a second send. pending +
    due now. ``actor_type``/``actor_id``/``transition_event`` persist the already-approved workflow intent so a
    DEFERRED delivery (background processor) can replay exactly that transition — never inventing a new one.
    Returns {message_id, status, deduped}."""
    if db is None or not idempotency_key:
        return {"message_id": None, "status": "skipped", "deduped": False}
    ts = _now_iso(now_iso)
    try:
        db.execute(text(_DDL))
        existing = db.execute(text("SELECT id, status FROM outbound_message WHERE tenant_id=:t AND idempotency_key=:k LIMIT 1"),
                              {"t": tenant_id, "k": idempotency_key}).fetchone()
        if existing:
            return {"message_id": existing[0], "status": existing[1], "deduped": True}
        mid = f"out-{uuid.uuid4().hex[:12]}"
        db.execute(text(
            "INSERT INTO outbound_message (id, tenant_id, case_id, recipient, subject, body, idempotency_key, "
            "status, attempts, max_attempts, next_attempt_at, ack_status, actor_type, actor_id, transition_event, "
            "created_at, updated_at) "
            "VALUES (:i,:t,:c,:r,:s,:b,:k,'pending',0,:m,:n,'awaiting',:at,:ai,:te,:ts,:ts)"),
            {"i": mid, "t": tenant_id, "c": case_id, "r": recipient, "s": subject, "b": body,
             "k": idempotency_key, "m": int(max_attempts), "n": ts, "at": actor_type, "ai": actor_id,
             "te": transition_event, "ts": ts})
        db.commit()
        return {"message_id": mid, "status": "pending", "deduped": False}
    except Exception as exc:
        logger.debug("outbound enqueue failed for %s: %s", case_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return {"message_id": None, "status": "error", "deduped": False}


def _reclaim_stale(db, *, tenant_id: str, ts: str) -> None:
    """A row claimed ('sending') by a worker that then crashed is reset to 'pending' once its claim ages past
    OUTBOUND_STALE_CLAIM_SEC, so it is retried rather than stranded. Idempotency on content_hash keeps the
    eventual resend at-least-once-safe for a transport that honours it."""
    cutoff = _plus_seconds(ts, -_stale_claim_seconds())
    db.execute(text("UPDATE outbound_message SET status='pending', updated_at=:ts WHERE tenant_id=:t "
                    "AND status='sending' AND updated_at < :cut"), {"ts": ts, "t": tenant_id, "cut": cutoff})


def process_pending(db, *, transport: Optional[Any] = None, tenant_id: str = "default",
                    limit: int = 50, only_key: str = "", now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Attempt every DUE pending message once. Each row is ATOMICALLY CLAIMED (pending→sending) before transmit
    so two workers can never both send it (the loser's claim affects 0 rows and is skipped); the result is
    committed PER ROW so a crash after transmit leaves the row 'sending' (recoverable, NOT re-sent) rather than
    'pending' (which would re-send). On success → sent (+ provider_ref); on failure → backoff retry, or
    dead_letter at max_attempts. Returns {processed, sent, retried, dead_lettered, sent_rows} where sent_rows
    carries the approved transition intent for a workflow-aware caller to replay (fixes deferred-send stranding).
    ``only_key`` scopes the drive to a single message (the synchronous send path)."""
    if db is None:
        return {"processed": 0, "sent": 0, "retried": 0, "dead_lettered": 0, "sent_rows": []}
    tx = transport or _default_transport()
    ts = _now_iso(now_iso)
    out: Dict[str, Any] = {"processed": 0, "sent": 0, "retried": 0, "dead_lettered": 0, "sent_rows": []}
    try:
        db.execute(text(_DDL))
        _reclaim_stale(db, tenant_id=tenant_id, ts=ts)
        sql = ("SELECT id, case_id, recipient, subject, body, idempotency_key, attempts, max_attempts, "
               "actor_type, actor_id, transition_event FROM outbound_message WHERE tenant_id=:t AND status='pending' "
               "AND (next_attempt_at IS NULL OR next_attempt_at <= :ts) ")
        params: Dict[str, Any] = {"t": tenant_id, "ts": ts, "lim": int(limit)}
        if only_key:
            sql += "AND idempotency_key=:k "
            params["k"] = only_key
        sql += "ORDER BY created_at ASC LIMIT :lim"
        rows = db.execute(text(sql), params).fetchall()
        db.commit()
    except Exception as exc:
        logger.debug("process_pending query failed: %s", exc)
        return out
    for r in (rows or []):
        mid, case_id, recipient, subject, body, idem, attempts, max_attempts, a_type, a_id, t_event = r
        # ATOMIC CLAIM: only the worker whose UPDATE flips pending→sending may transmit (rowcount guard).
        try:
            claim = db.execute(text("UPDATE outbound_message SET status='sending', attempts=attempts+1, "
                                    "updated_at=:ts WHERE id=:i AND status='pending'"), {"ts": ts, "i": mid})
            db.commit()
        except Exception as exc:
            logger.warning("outbound claim failed for %s: %s", mid, exc)
            try:
                db.rollback()
            except Exception:
                pass
            continue
        if getattr(claim, "rowcount", 0) != 1:
            continue  # another worker claimed it first
        out["processed"] += 1
        new_attempts = int(attempts or 0) + 1
        try:
            res = tx.send(to=recipient, subject=subject, body=body, idempotency_key=str(idem or ""))
            status = getattr(res, "status", "failed")
            provider_ref = getattr(res, "provider_ref", "") or ""
            detail = getattr(res, "detail", "") or ""
        except Exception as exc:
            status, provider_ref, detail = "failed", "", str(exc)[:200]
        try:
            if status == "sent":
                db.execute(text("UPDATE outbound_message SET status='sent', provider_ref=:p, updated_at=:ts "
                                "WHERE id=:i"), {"p": provider_ref, "ts": ts, "i": mid})
                db.commit()
                out["sent"] += 1
                out["sent_rows"].append({"case_id": case_id, "content_hash": idem, "provider_ref": provider_ref,
                                         "actor_type": a_type or "", "actor_id": a_id or "",
                                         "transition_event": t_event or ""})
            elif new_attempts >= int(max_attempts or 5):
                db.execute(text("UPDATE outbound_message SET status='dead_letter', last_error=:e, updated_at=:ts "
                                "WHERE id=:i"), {"e": detail, "ts": ts, "i": mid})
                db.commit()
                out["dead_lettered"] += 1
            else:
                nxt = _plus_seconds(ts, _backoff_seconds(new_attempts))
                db.execute(text("UPDATE outbound_message SET status='pending', next_attempt_at=:n, last_error=:e, "
                                "updated_at=:ts WHERE id=:i"), {"n": nxt, "e": detail, "ts": ts, "i": mid})
                db.commit()
                out["retried"] += 1
        except Exception as exc:
            # Commit of the RESULT failed. The row stays 'sending' (not 'pending'), so it is NOT re-sent on the
            # next pass — only reclaimed after the stale window. Surface loudly; never swallow silently.
            logger.error("outbound result-commit failed for %s (transport status=%s) — row left 'sending' for "
                         "stale-reclaim: %s", mid, status, exc)
            try:
                db.rollback()
            except Exception:
                pass
    return out


def get_by_key(db, *, idempotency_key: str, tenant_id: str = "default") -> Dict[str, Any]:
    """Read one message's reliability state by content_hash — {status, provider_ref, attempts, ack_status}."""
    if db is None or not idempotency_key:
        return {}
    try:
        db.execute(text(_DDL))
        r = db.execute(text("SELECT status, provider_ref, attempts, ack_status, last_error FROM outbound_message "
                            "WHERE tenant_id=:t AND idempotency_key=:k LIMIT 1"),
                       {"t": tenant_id, "k": idempotency_key}).fetchone()
        if not r:
            return {}
        return {"status": r[0], "provider_ref": r[1] or "", "attempts": int(r[2] or 0),
                "ack_status": r[3], "last_error": r[4] or ""}
    except Exception:
        return {}


def send_now(db, *, case_id: str, recipient: str, subject: str, body: str, idempotency_key: str,
             transport: Optional[Any] = None, max_attempts: int = 5, tenant_id: str = "default",
             actor_type: str = "", actor_id: str = "", transition_event: str = "",
             now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Synchronous RELIABLE send for the GATE-2 path: durably enqueue (idempotent on content_hash) then attempt
    THIS message once. Returns {status, provider_ref, detail}: 'sent' (caller transitions now), or 'pending'
    (transient failure — durably retryable by the background processor, the human can re-dispatch), or
    'dead_letter'. The actor/event are persisted so a DEFERRED delivery replays the SAME approved transition.
    Preserves the human-only send invariant: it only sends what the caller already approved, and a re-dispatch
    of the same content_hash never double-sends (deduped)."""
    enqueue(db, case_id=case_id, recipient=recipient, subject=subject, body=body, idempotency_key=idempotency_key,
            max_attempts=max_attempts, tenant_id=tenant_id, actor_type=actor_type, actor_id=actor_id,
            transition_event=transition_event, now_iso=now_iso)
    existing = get_by_key(db, idempotency_key=idempotency_key, tenant_id=tenant_id)
    if existing.get("status") == "sent":  # idempotent re-dispatch of an already-delivered message
        return {"status": "sent", "provider_ref": existing.get("provider_ref", ""), "detail": "deduped"}
    if existing.get("status") == "sending":  # claimed by a concurrent worker — do NOT re-send; let it settle
        return {"status": "pending", "provider_ref": "", "detail": "in_flight"}
    process_pending(db, transport=transport, tenant_id=tenant_id, only_key=idempotency_key, now_iso=now_iso)
    row = get_by_key(db, idempotency_key=idempotency_key, tenant_id=tenant_id)
    return {"status": row.get("status", "pending"), "provider_ref": row.get("provider_ref", ""),
            "detail": row.get("last_error", "")}


def record_ack(db, *, idempotency_key: str, ack_ref: str = "", case_id: str = "", tenant_id: str = "default",
               now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Record the supplier's acknowledgement (EDI 855) — but ONLY for a message that was actually SENT (you
    cannot acknowledge an unsent draft), and ONLY when the optional ``case_id`` matches the row (so an ack can't
    be routed to the wrong case). Returns {acked, message_id, reason}."""
    if db is None or not idempotency_key:
        return {"acked": False, "message_id": None, "reason": "no_key"}
    ts = _now_iso(now_iso)
    try:
        db.execute(text(_DDL))
        row = db.execute(text("SELECT id, status, case_id FROM outbound_message WHERE tenant_id=:t "
                              "AND idempotency_key=:k LIMIT 1"), {"t": tenant_id, "k": idempotency_key}).fetchone()
        if not row:
            return {"acked": False, "message_id": None, "reason": "not_found"}
        if row[1] != "sent":
            return {"acked": False, "message_id": row[0], "reason": f"not_sent:{row[1]}"}
        if case_id and str(row[2] or "") != str(case_id):
            return {"acked": False, "message_id": row[0], "reason": "case_mismatch"}
        db.execute(text("UPDATE outbound_message SET ack_status='acked', acked_at=:ts, provider_ref="
                        "COALESCE(NULLIF(:ar,''), provider_ref), updated_at=:ts WHERE id=:i AND status='sent'"),
                   {"ts": ts, "ar": ack_ref, "i": row[0]})
        db.commit()
        return {"acked": True, "message_id": row[0], "reason": "ok"}
    except Exception as exc:
        logger.debug("record_ack failed for %s: %s", idempotency_key, exc)
        return {"acked": False, "message_id": None, "reason": "error"}


def queue_status(db, *, tenant_id: str = "default") -> Dict[str, Any]:
    """Counts by status + unacknowledged-sent count — the operator/observability view."""
    if db is None:
        return {}
    try:
        db.execute(text(_DDL))
        rows = db.execute(text("SELECT status, COUNT(*) FROM outbound_message WHERE tenant_id=:t GROUP BY status"),
                          {"t": tenant_id}).fetchall()
        by_status = {str(r[0]): int(r[1]) for r in (rows or [])}
        unacked = db.execute(text("SELECT COUNT(*) FROM outbound_message WHERE tenant_id=:t AND status='sent' "
                                  "AND ack_status<>'acked'"), {"t": tenant_id}).fetchone()
        return {"by_status": by_status, "unacknowledged_sent": int((unacked or [0])[0] or 0)}
    except Exception:
        return {}


def dead_letters(db, *, tenant_id: str = "default", limit: int = 50) -> List[Dict[str, Any]]:
    """The messages that exhausted their retries — the operator triage queue."""
    if db is None:
        return []
    try:
        db.execute(text(_DDL))
        rows = db.execute(text("SELECT id, case_id, recipient, subject, attempts, last_error, updated_at "
                               "FROM outbound_message WHERE tenant_id=:t AND status='dead_letter' "
                               "ORDER BY updated_at DESC LIMIT :lim"), {"t": tenant_id, "lim": int(limit)}).fetchall()
        return [{"id": r[0], "case_id": r[1], "recipient": r[2], "subject": r[3], "attempts": int(r[4] or 0),
                 "last_error": r[5] or "", "updated_at": r[6]} for r in (rows or [])]
    except Exception:
        return []


def _default_transport() -> Any:
    """Pick the transport the same way external_comms does — SMTP when FULFILLMENT_SUPPLIER_TRANSPORT=smtp,
    else sandbox. No secrets read here beyond what SmtpTransport reads at deploy."""
    from src.app.services.fulfillment.transport import SandboxTransport, SmtpTransport
    if str(os.getenv("FULFILLMENT_SUPPLIER_TRANSPORT", "sandbox")).strip().lower() == "smtp":
        return SmtpTransport()
    return SandboxTransport()
