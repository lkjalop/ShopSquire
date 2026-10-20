"""Money-P0 M3 — refund execution state + idempotent retry (GPT-5.6 review-11b #6).

The gap: a refund APPROVAL is recorded before the provider refund call; if the provider fails, the
approval is on file but the money never moved — and re-calling approve returns `no_open_refund_request`
(the approval already exists), so there is no way to RETRY the execution. The "operator can retry"
comment was not backed by anything.

This records each approved refund as a durable EXECUTION (state=pending) keyed by the SAME provider
idempotency_key the approval uses (`refund:{order}:{index}`). Retrying re-issues the provider refund
with that key → the provider returns the SAME refund, never a second one. A worker drives
pending/failed executions to settled. State: pending -> settled | failed (retryable).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import inspect, text

logger = logging.getLogger("shopsquire.refund_execution")

DEFAULT_TENANT = "default"
STATE_PENDING = "pending"
STATE_PROCESSING = "processing"
STATE_SUBMITTED = "provider_submitted"
STATE_SETTLED = "settled"
STATE_FAILED = "failed"

_DDL = """
CREATE TABLE IF NOT EXISTS refund_executions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    order_id TEXT NOT NULL,
    approval_index INTEGER,
    amount_cents INTEGER,
    currency TEXT,
    intent_id TEXT,
    idempotency_key TEXT NOT NULL,
    state TEXT NOT NULL,
    provider_ref TEXT,
    error TEXT,
    attempts INTEGER DEFAULT 0,
    claim_token TEXT,
    lease_expires_at REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_refund_exec_key ON refund_executions(idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_refund_exec_state ON refund_executions(state)",
)


def ensure_table(db) -> None:
    if db is None:
        return
    inspector = inspect(db.connection())
    if not inspector.has_table('refund_executions'):
        db.execute(text(_DDL))
    columns = {c["name"] for c in inspector.get_columns("refund_executions")}
    if "claim_token" not in columns:
        db.execute(text("ALTER TABLE refund_executions ADD COLUMN claim_token TEXT"))
    if "lease_expires_at" not in columns:
        db.execute(text("ALTER TABLE refund_executions ADD COLUMN lease_expires_at REAL"))
    for name, kind in [('effect_digest', 'TEXT'), ('authorized_until', 'REAL'), ('revoked_at', 'REAL')]:
        if name not in columns:
            db.execute(text(f'ALTER TABLE refund_executions ADD COLUMN {name} {kind}'))
    indexes = {i['name'] for i in inspector.get_indexes('refund_executions')}
    for idx in _INDEXES:
        if idx.split(' ON ', 1)[0].split()[-1] not in indexes:
            db.execute(text(idx))


def open_execution(db, *, order_id: str, approval_index: int, amount_cents: Optional[int],
                   currency: str, intent_id: Optional[str], idempotency_key: str,
                   tenant_id: str = DEFAULT_TENANT, commit: bool = True,
                   authorized_until: Optional[float] = None) -> str:
    """Durably record an approved refund as a PENDING execution. UNIQUE(idempotency_key) → an
    approval retried / re-approved reuses the SAME row (no duplicate execution). Returns the row id."""
    ensure_table(db)
    from src.app.services.refund_authorization import refund_effect_digest
    digest = refund_effect_digest(tenant_id=str(tenant_id or DEFAULT_TENANT), order_id=str(order_id),
        approval_index=int(approval_index), amount_cents=int(amount_cents) if amount_cents is not None else None,
        currency=str(currency or 'USD')[:3], intent_id=str(intent_id) if intent_id else None,
        idempotency_key=str(idempotency_key))
    rid = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}"
    db.execute(text(
        "INSERT INTO refund_executions (id, tenant_id, order_id, approval_index, amount_cents, "
        "currency, intent_id, idempotency_key, state, effect_digest, authorized_until) "
        "VALUES (:i,:t,:o,:ai,:a,:c,:pi,:k,:s,:digest,:expiry) ON CONFLICT (idempotency_key) DO NOTHING"),
        {"i": rid, "t": str(tenant_id or DEFAULT_TENANT), "o": str(order_id), "ai": int(approval_index),
         "a": (int(amount_cents) if amount_cents is not None else None), "c": str(currency or "USD")[:3],
         "pi": (str(intent_id) if intent_id else None), "k": str(idempotency_key), "s": STATE_PENDING,
         "digest": digest, "expiry": time.time()+86400 if authorized_until is None else float(authorized_until)})
    row = db.execute(text("SELECT id, tenant_id, order_id, approval_index, amount_cents, currency, intent_id "
                          "FROM refund_executions WHERE idempotency_key = :k"),
                     {"k": str(idempotency_key)}).fetchone()
    expected = (str(tenant_id or DEFAULT_TENANT), str(order_id), int(approval_index),
                int(amount_cents) if amount_cents is not None else None, str(currency or "USD")[:3],
                str(intent_id) if intent_id else None)
    if row is None:
        raise RuntimeError('refund_execution_not_persisted')
    if tuple(row[1:]) != expected:
        raise ValueError("refund_effect_binding_conflict")
    if commit:
        db.commit()
    return str(row[0])


def _set(db, exec_id: str, state: str, *, provider_ref: Optional[str] = None,
         error: Optional[str] = None, bump: bool = False, commit: bool = True,
         claim_token: Optional[str] = None) -> bool:
    sets = ["state = :s", "updated_at = CURRENT_TIMESTAMP"]
    params: Dict[str, Any] = {"s": state, "id": exec_id}
    if provider_ref is not None:
        sets.append("provider_ref = :pr"); params["pr"] = str(provider_ref)
    if error is not None:
        sets.append("error = :e"); params["e"] = str(error)[:400]
    if bump:
        sets.append("attempts = attempts + 1")
    guard = ''
    if claim_token is not None:
        guard = " AND claim_token=:claim AND state='processing'"
        params['claim'] = claim_token
    result = db.execute(text(f"UPDATE refund_executions SET {', '.join(sets)} WHERE id = :id" + guard), params)
    if commit:
        db.commit()
    return int(result.rowcount or 0) == 1


def mark_settled(db, exec_id: str, *, provider_ref: Optional[str], commit: bool = True,
                 claim_token: Optional[str] = None) -> bool:
    return _set(db, exec_id, STATE_SETTLED, provider_ref=provider_ref, commit=commit, claim_token=claim_token)


def mark_failed(db, exec_id: str, *, error: str, commit: bool = True,
                claim_token: Optional[str] = None) -> bool:
    return _set(db, exec_id, STATE_FAILED, error=error, bump=True, commit=commit, claim_token=claim_token)


def mark_submitted(db, exec_id: str, *, provider_ref: Optional[str], commit: bool = True,
                   claim_token: Optional[str] = None) -> bool:
    return _set(db, exec_id, STATE_SUBMITTED, provider_ref=provider_ref, commit=commit, claim_token=claim_token)


def settle_submitted_for_intent(db, *, intent_id: str, provider_ref: Optional[str] = None,
                                commit: bool = True) -> int:
    if not provider_ref:
        return 0  # payment-intent identity alone cannot settle distinct partial refunds
    result = db.execute(text(
        "UPDATE refund_executions SET state=:settled, provider_ref=COALESCE(:pr,provider_ref), "
        "claim_token=NULL,lease_expires_at=NULL,updated_at=CURRENT_TIMESTAMP "
        "WHERE intent_id=:pi AND provider_ref=:pr AND state=:submitted"
    ), {"settled": STATE_SETTLED, "submitted": STATE_SUBMITTED, "pi": str(intent_id),
        "pr": (str(provider_ref) if provider_ref else None)})
    if commit:
        db.commit()
    return int(result.rowcount or 0)


def _default_refund_fn(intent_id: str, amount_cents: Optional[int], idempotency_key: str) -> Dict[str, Any]:
    """Execute the provider refund with the stored idempotency_key (Stripe dedups → no double refund)."""
    from src.app.config import get_settings
    from src.app.services.payments import StripeClient
    settings = get_settings()
    client = StripeClient(settings.stripe_api_key)
    return client.create_refund(payment_intent_id=intent_id, amount_cents=amount_cents,
                                reason="requested_by_customer", idempotency_key=idempotency_key)


def revoke_pending(db, *, exec_id: str, tenant_id: str) -> bool:
    """Revoke an unclaimed effect. False means dispatch may already have begun."""
    result = db.execute(text("UPDATE refund_executions SET revoked_at=:now "
        "WHERE id=:id AND tenant_id=:tenant AND state IN ('pending','failed') AND revoked_at IS NULL"),
        {'now':time.time(), 'id':exec_id, 'tenant':tenant_id})
    db.commit()
    return int(result.rowcount or 0) == 1


def execute_pending(db, *, tenant_id: str = DEFAULT_TENANT, limit: int = 20,
                    order_id: Optional[str] = None,
                    exec_id: Optional[str] = None,
                    refund_fn: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Drive pending/failed executions to settled — idempotently (same key → same provider refund).
    Only rows with a real (non-demo) intent are executable. order_id scopes to one order (the retry
    endpoint); omitted = every pending in the tenant (the worker). Best-effort; never raises."""
    ensure_table(db)
    fn = refund_fn or _default_refund_fn
    _order_clause = " AND order_id = :oid" if order_id else ""
    _params: Dict[str, Any] = {"t": str(tenant_id or DEFAULT_TENANT), "lim": int(limit)}
    if order_id:
        _params["oid"] = str(order_id)
    if exec_id:
        _order_clause += ' AND id=:execution_id'
        _params['execution_id'] = exec_id
    try:
        rows = db.execute(text(
            "SELECT * FROM refund_executions "
            "WHERE (state IN ('pending','failed') OR "
            "(state='processing' AND lease_expires_at < :now)) AND intent_id IS NOT NULL AND intent_id != '' "
            "AND intent_id NOT LIKE 'pi_demo_%' AND COALESCE(tenant_id,'default') = :t"
            + _order_clause + " ORDER BY created_at ASC LIMIT :lim"),
            {**_params, "now": time.time()}).mappings().all()
    except Exception as exc:
        logger.warning("execute_pending read failed: %s", repr(exc)[:120])
        return {"settled": 0, "failed": 0, "checked": 0}
    settled = failed = 0
    for r in rows or []:
        from src.app.services.refund_authorization import refund_permit_current
        if not refund_permit_current(r):
            continue
        eid, oid, amt, intent, key = r['id'], r['order_id'], r['amount_cents'], r['intent_id'], r['idempotency_key']
        token = uuid.uuid4().hex
        claim = db.execute(text(
            "UPDATE refund_executions SET state=:processing,claim_token=:token,"
            "lease_expires_at=:lease,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND "
            "(state IN ('pending','failed') OR (state='processing' AND lease_expires_at < :now)) "
            "AND tenant_id=:tenant AND effect_digest=:digest AND authorized_until>:now AND revoked_at IS NULL "
            "AND order_id=:oid AND approval_index=:approval AND currency=:currency "
            "AND intent_id=:intent AND idempotency_key=:key "
            "AND (amount_cents=:amount OR (amount_cents IS NULL AND CAST(:amount AS BIGINT) IS NULL))"
        ), {"processing": STATE_PROCESSING, "token": token, "lease": time.time() + 60.0,
            "id": eid, "now": time.time(), 'tenant':r['tenant_id'], 'digest':r['effect_digest'],
            'oid':oid, 'approval':r['approval_index'], 'currency':r['currency'],
            'intent':intent, 'key':key, 'amount':amt})
        db.commit()
        if int(claim.rowcount or 0) != 1:
            continue
        try:
            refund = fn(intent, (int(amt) if amt is not None else None), key)
            if not str((refund or {}).get('id') or '').startswith('re_'):
                raise ValueError('exact_refund_receipt_required')
            if ((refund or {}).get('payment_intent', intent) != intent
                    or (amt is not None and (refund or {}).get('amount', amt) != amt)):
                raise ValueError('refund_receipt_effect_mismatch')
            status = str((refund or {}).get("status") or "").lower()
            if status == "succeeded":
                settled += int(mark_settled(db, eid, provider_ref=refund['id'], claim_token=token))
            elif status in {'pending', 'requires_action'}:
                mark_submitted(db, eid, provider_ref=refund['id'], claim_token=token)
            else:
                raise ValueError('refund_receipt_not_successful')
        except Exception as exc:
            db.rollback()
            failed += int(mark_failed(db, eid, error=repr(exc)[:200], claim_token=token))
            logger.warning("refund execution retry failed (order=%s): %s", oid, repr(exc)[:120])
    return {"settled": settled, "failed": failed, "checked": len(rows or [])}
