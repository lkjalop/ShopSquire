"""Append-only payment transaction ledger (agnostic CORE).

Until now payment state was ONE mutable string on the orders row — no history, no amounts, no
actor, nothing for a refund or dispute to reconcile against. This ledger records every payment
event as an immutable row (append-only: the module exposes no UPDATE path), so:
  * "what happened to this order's money" is answerable event-by-event,
  * refunds are a governed two-step (requested → approved) with the actor recorded,
  * the settlement webhook RECONCILES against the ledger instead of silently flipping status.

Vertical-blind: order ids / intent ids / cents / kinds only. Best-effort writes; never raises
into a request path. Idempotent table creation (SQLite + Postgres portable).
"""
from __future__ import annotations

import logging
import time
import uuid

_log = logging.getLogger("shopsquire.payment_ledger")
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

# Event kinds (append-only vocabulary; consumers must tolerate unknown kinds).
KIND_INTENT_CREATED = "intent_created"
KIND_PAYMENT_SUCCEEDED = "payment_succeeded"
KIND_PAYMENT_FAILED = "payment_failed"
KIND_DISPATCH_QUEUED = "dispatch_queued"
KIND_REFUND_REQUESTED = "refund_requested"
KIND_REFUND_APPROVED = "refund_approved"
KIND_REFUND_SETTLED = "refund_settled"

_DDL = """
CREATE TABLE IF NOT EXISTS payment_transactions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    order_id TEXT,
    intent_id TEXT,
    kind TEXT,
    amount_cents INTEGER,
    currency TEXT,
    provider TEXT,
    actor_type TEXT,
    actor_id TEXT,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_payment_txn_order ON payment_transactions(tenant_id, order_id)",
    "CREATE INDEX IF NOT EXISTS ix_payment_txn_intent ON payment_transactions(intent_id)",
)


def ensure_table(db) -> None:
    if db is None:
        return
    db.execute(text(_DDL))
    for idx in _INDEXES:
        db.execute(text(idx))


def record_txn(db, *, order_id: str, kind: str, intent_id: Optional[str] = None,
               amount_cents: Optional[int] = None, currency: str = "USD", provider: str = "",
               actor_type: str = "", actor_id: str = "", reason: str = "",
               tenant_id: str = DEFAULT_TENANT, commit: bool = False) -> Optional[str]:
    """Append one payment event → returns the row id. FAIL-CLOSED (Track A A2): the payment ledger
    is the source of truth for the refund fold, so a lost write = under-counted refunds =
    double-refund/reconciliation risk. This therefore RAISES on write failure (was silently
    'best-effort; never raises') so the money action fails rather than proceeding un-recorded.
    Callers that are genuinely best-effort (intent-created, dispatch-queued) already wrap the
    call; the refund-approval path (which was NOT wrapped) now correctly fails closed — no ledger
    record, no refund executed."""
    if db is None or not str(order_id or "").strip() or not str(kind or "").strip():
        return None
    try:
        ensure_table(db)
        # time-prefixed id → ORDER BY id is insertion order even within one timestamp second
        # (created_at has second precision; the refund fold depends on stable event order).
        tid = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}"
        db.execute(text(
            "INSERT INTO payment_transactions (id, tenant_id, order_id, intent_id, kind, amount_cents, "
            "currency, provider, actor_type, actor_id, reason) "
            "VALUES (:i,:t,:o,:pi,:k,:a,:c,:p,:at,:ai,:r)"),
            {"i": tid, "t": str(tenant_id or DEFAULT_TENANT), "o": str(order_id), "pi": (str(intent_id) if intent_id else None),
             "k": str(kind)[:40], "a": (int(amount_cents) if amount_cents is not None else None),
             "c": str(currency or "USD")[:3], "p": str(provider or "")[:40],
             "at": str(actor_type or "")[:20], "ai": str(actor_id or "")[:80], "r": str(reason or "")[:500]})
        if commit:
            db.commit()
        return tid
    except Exception as exc:
        _log.error("payment ledger write FAILED (failing closed) order=%s kind=%s: %s",
                   order_id, kind, repr(exc)[:160])
        raise


def reserve_refund_slot(db, token: str) -> bool:
    """Atomic single-winner lock for a refund request/approval slot (P0-1f). The refund rail's
    'one open request' and 'one approval per request' invariants were enforced by counting the
    ledger then appending — check-then-act, so two concurrent refunds could both pass and both
    append (double open request → double approval → double refund). This reserves a UNIQUE(key)
    row so exactly one caller wins a given (order, count) slot.

    Does NOT commit — it rides the CALLER'S transaction so the reservation and the ledger append
    commit together: if the append fails and the session rolls back, the slot is released (never a
    permanently-burned key). INSERT ... ON CONFLICT DO NOTHING is concurrency-safe (the second txn
    blocks on the row until the first commits, then sees it → rowcount 0). Fail-CLOSED: on DB error
    we return False (reject) — for money-OUT, blocking is the safe direction."""
    if db is None or not str(token or "").strip():
        return False
    try:
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS idempotency_keys "
            "(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response_status INT, "
            "response_body TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        res = db.execute(text(
            "INSERT INTO idempotency_keys (key, fingerprint) VALUES (:k, 'refund_slot') "
            "ON CONFLICT (key) DO NOTHING"), {"k": str(token)})
        return int(getattr(res, "rowcount", 0) or 0) == 1
    except Exception as exc:
        _log.warning("refund slot reservation failed (failing closed) token=%s: %s", token, repr(exc)[:120])
        try:
            db.rollback()
        except Exception:
            pass
        return False


def ledger_for_order(db, order_id: str, *, tenant_id: str = DEFAULT_TENANT, limit: int = 100) -> List[Dict[str, Any]]:
    """All ledger events for one order, oldest first. Best-effort; never raises."""
    if db is None or not order_id:
        return []
    try:
        ensure_table(db)
        rows = db.execute(text(
            "SELECT kind, intent_id, amount_cents, currency, provider, actor_type, actor_id, reason, created_at "
            "FROM payment_transactions WHERE COALESCE(tenant_id,'default')=:t AND order_id=:o "
            "ORDER BY id ASC LIMIT :lim"),
            {"t": str(tenant_id or DEFAULT_TENANT), "o": str(order_id), "lim": int(limit)}).fetchall()
    except Exception:
        return []
    return [{"kind": r[0], "intent_id": r[1], "amount_cents": r[2], "currency": r[3], "provider": r[4],
             "actor_type": r[5], "actor_id": r[6], "reason": r[7], "created_at": r[8]} for r in rows]


def refund_state(db, order_id: str, *, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Any]:
    """Fold the ledger into the current refund position for one order:
    {captured_cents, requested_cents, approved_cents, settled_cents, open_request}.
    open_request is True when a refund_requested has no matching approval yet (one open at a time —
    the governed two-step). Best-effort; empty/zeroed on failure."""
    out = {"captured_cents": 0, "requested_cents": 0, "approved_cents": 0, "settled_cents": 0,
           "open_request": False, "requests": 0, "approvals": 0}
    events = ledger_for_order(db, order_id, tenant_id=tenant_id)
    requests = approvals = 0
    for e in events:
        amt = int(e.get("amount_cents") or 0)
        k = e.get("kind")
        if k == KIND_PAYMENT_SUCCEEDED:
            out["captured_cents"] += amt
        elif k == KIND_REFUND_REQUESTED:
            out["requested_cents"] += amt
            requests += 1
        elif k == KIND_REFUND_APPROVED:
            out["approved_cents"] += amt
            approvals += 1
        elif k == KIND_REFUND_SETTLED:
            out["settled_cents"] += amt
    out["open_request"] = requests > approvals
    out["requests"], out["approvals"] = requests, approvals   # counts for the P0-1f slot lock
    return out
