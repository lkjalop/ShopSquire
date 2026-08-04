"""Durable payment-attempt record + transactional outbox (Money-P0 M1, GPT-5.6 review-11b #3).

The failure GPT-5.6 named: checkout creates a Stripe PaymentIntent, THEN best-effort writes the
`stripe_intent_id` onto the order and a ledger row. If those writes are lost (DB blip, crash), the
intent exists AT THE PROVIDER with no local association — the webhook finds the order by
`stripe_intent_id` and can never transition it → an orphan charge.

This makes the association RECOVERABLE. Before the provider call we durably record an ATTEMPT
(state=reserved). After the provider returns we record its `provider_ref` (state=provider_created)
— so even if the order-association write is then lost, the attempt row still carries
(order_id, provider_ref) and `reconcile_orphans()` re-applies the association. The attempt id is
also the natural idempotency anchor for the provider call.

State machine:  reserved -> provider_created -> associated
                                              -> failed
Vertical-blind, best-effort table creation (SQLite + Postgres). record_txn stays the money ledger;
this is the association-integrity layer beside it.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger("shopsquire.payment_attempts")

DEFAULT_TENANT = "default"

STATE_RESERVED = "reserved"
STATE_PROVIDER_CREATED = "provider_created"
STATE_ASSOCIATED = "associated"
STATE_FAILED = "failed"

_DDL = """
CREATE TABLE IF NOT EXISTS payment_attempts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    order_id TEXT,
    provider TEXT,
    provider_ref TEXT,
    amount_cents INTEGER,
    currency TEXT,
    idempotency_key TEXT,
    state TEXT NOT NULL,
    error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_payment_attempts_state ON payment_attempts(state)",
    "CREATE INDEX IF NOT EXISTS ix_payment_attempts_order ON payment_attempts(order_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_payment_attempts_ref ON payment_attempts(provider, provider_ref)",
)


def ensure_table(db) -> None:
    if db is None:
        return
    db.execute(text(_DDL))
    for idx in _INDEXES:
        try:
            db.execute(text(idx))
        except Exception:
            pass   # a legacy row set may not satisfy the unique index yet; index is best-effort


def open_attempt(db, *, order_id: Optional[str], provider: str, amount_cents: Optional[int],
                 currency: str = "USD", idempotency_key: Optional[str] = None,
                 tenant_id: str = DEFAULT_TENANT, commit: bool = True) -> str:
    """Durably record an attempt BEFORE the provider call → returns the attempt id. FAIL-CLOSED:
    raises on write failure (a payment that can't be recorded must not proceed)."""
    ensure_table(db)
    aid = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}"
    db.execute(text(
        "INSERT INTO payment_attempts (id, tenant_id, order_id, provider, amount_cents, currency, "
        "idempotency_key, state) VALUES (:i,:t,:o,:p,:a,:c,:k,:s)"),
        {"i": aid, "t": str(tenant_id or DEFAULT_TENANT), "o": (str(order_id) if order_id else None),
         "p": str(provider or "")[:40], "a": (int(amount_cents) if amount_cents is not None else None),
         "c": str(currency or "USD")[:3], "k": (str(idempotency_key) if idempotency_key else None),
         "s": STATE_RESERVED})
    if commit:
        db.commit()
    return aid


def _set_state(db, attempt_id: str, state: str, *, provider_ref: Optional[str] = None,
               order_id: Optional[str] = None, error: Optional[str] = None, commit: bool = True) -> None:
    sets = ["state = :s", "updated_at = CURRENT_TIMESTAMP"]
    params: Dict[str, Any] = {"s": state, "id": attempt_id}
    if provider_ref is not None:
        sets.append("provider_ref = :pr"); params["pr"] = str(provider_ref)
    if order_id is not None:
        sets.append("order_id = :o"); params["o"] = str(order_id)
    if error is not None:
        sets.append("error = :e"); params["e"] = str(error)[:500]
    db.execute(text(f"UPDATE payment_attempts SET {', '.join(sets)} WHERE id = :id"), params)
    if commit:
        db.commit()


def mark_provider_created(db, attempt_id: str, *, provider_ref: str,
                          order_id: Optional[str] = None, commit: bool = True) -> None:
    """The provider created the intent — record its ref durably so a lost association is repairable."""
    _set_state(db, attempt_id, STATE_PROVIDER_CREATED, provider_ref=provider_ref,
               order_id=order_id, commit=commit)


def mark_associated(db, attempt_id: str, *, commit: bool = True) -> None:
    _set_state(db, attempt_id, STATE_ASSOCIATED, commit=commit)


def mark_failed(db, attempt_id: str, *, error: str = "", commit: bool = True) -> None:
    _set_state(db, attempt_id, STATE_FAILED, error=error, commit=commit)


def reconcile_orphans(db, *, tenant_id: str = DEFAULT_TENANT, limit: int = 50) -> Dict[str, Any]:
    """The OUTBOX reader: an attempt stuck in provider_created (the provider made the intent but the
    order-association write was lost) is repaired — re-apply stripe_intent_id + the ledger row, then
    mark associated. Idempotent: only touches orders whose intent isn't already set. Best-effort;
    returns a summary. Run from a worker / on startup."""
    ensure_table(db)
    try:
        rows = db.execute(text(
            "SELECT id, order_id, provider_ref, amount_cents, currency, provider "
            "FROM payment_attempts WHERE state = :s AND order_id IS NOT NULL AND provider_ref IS NOT NULL "
            "AND COALESCE(tenant_id,'default') = :t ORDER BY created_at ASC LIMIT :lim"),
            {"s": STATE_PROVIDER_CREATED, "t": str(tenant_id or DEFAULT_TENANT), "lim": int(limit)}).fetchall()
    except Exception as exc:
        logger.warning("reconcile_orphans read failed: %s", repr(exc)[:120])
        return {"repaired": 0, "checked": 0, "error": repr(exc)[:120]}
    repaired = 0
    for r in rows or []:
        aid, order_id, ref = str(r[0]), str(r[1]), str(r[2])
        try:
            res = db.execute(text(
                "UPDATE orders SET stripe_intent_id = :ref, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = :oid AND (stripe_intent_id IS NULL OR stripe_intent_id = '')"),
                {"ref": ref, "oid": order_id})
            newly_linked = int(getattr(res, "rowcount", 0) or 0) > 0
            if newly_linked:
                try:
                    from src.app.services.payment_ledger import KIND_INTENT_CREATED, record_txn
                    record_txn(db, order_id=order_id, kind=KIND_INTENT_CREATED, intent_id=ref,
                               amount_cents=(int(r[3]) if r[3] is not None else None),
                               currency=str(r[4] or "USD"), provider=str(r[5] or "stripe"), commit=False)
                except Exception as _lex:
                    logger.warning("reconcile ledger write failed (order=%s): %s", order_id, repr(_lex)[:100])
            _set_state(db, aid, STATE_ASSOCIATED, commit=False)
            db.commit()
            if newly_linked:
                repaired += 1
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            logger.warning("reconcile_orphans repair failed (attempt=%s): %s", aid, repr(exc)[:120])
    return {"repaired": repaired, "checked": len(rows or [])}
