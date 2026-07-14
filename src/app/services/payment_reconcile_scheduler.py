"""Money-P0 M1 — the transactional-outbox READER (background reconciliation).

Periodically drives payment_attempts stuck in `provider_created` (the provider made the intent but
the order-association write was lost) to `associated`, re-applying the stripe_intent_id + ledger row.
Without a reader the durable attempt row is inert; with it, a lost association self-heals within one
interval. Mirrors the app's other schedulers (start_/stop_ + daemon thread + stop_event).
"""
from __future__ import annotations

import logging
import os
import threading

from sqlalchemy import text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.payment_reconcile_scheduler")

_STOP_ATTR = "payment_reconcile_scheduler_stop"
_THREAD_ATTR = "payment_reconcile_scheduler_thread"


def _enabled() -> bool:
    return str(os.getenv("PAYMENT_RECONCILE_SCHEDULER_ENABLED", "1") or "1").strip().lower() in (
        "1", "true", "yes", "on")


def _interval_sec() -> float:
    try:
        return max(15.0, float(os.getenv("PAYMENT_RECONCILE_INTERVAL_SEC", "60") or 60))
    except Exception:
        return 60.0


def run_once() -> int:
    """Reconcile every tenant with an orphaned attempt. Returns total repaired. Never raises."""
    repaired = 0
    try:
        from src.app.services.payment_attempts import ensure_table, reconcile_orphans
        with db_session() as db:
            ensure_table(db)
            try:
                tenants = [str(r[0]) for r in db.execute(text(
                    "SELECT DISTINCT COALESCE(tenant_id,'default') FROM payment_attempts "
                    "WHERE state = 'provider_created'")).fetchall()]
            except Exception:
                tenants = []
            for t in (tenants or ["default"]):
                out = reconcile_orphans(db, tenant_id=t)
                repaired += int(out.get("repaired") or 0)
    except Exception as exc:
        logger.warning("payment reconcile run failed: %s", repr(exc)[:120])
    if repaired:
        logger.info("payment reconcile repaired %d orphaned association(s)", repaired)
    return repaired


def start_payment_reconcile_scheduler(app=None):
    if not _enabled():
        return
    stop_event = threading.Event()

    def _loop():
        # one immediate pass on boot (repairs orphans from the previous run), then periodic.
        while not stop_event.is_set():
            try:
                run_once()
            except Exception as exc:
                logger.warning("payment reconcile loop error: %s", repr(exc)[:120])
            stop_event.wait(timeout=_interval_sec())

    th = threading.Thread(target=_loop, daemon=True, name="payment-reconcile-scheduler")
    th.start()
    if app is not None:
        setattr(app.state, _STOP_ATTR, stop_event)
        setattr(app.state, _THREAD_ATTR, th)


def stop_payment_reconcile_scheduler(app=None):
    if app is None:
        return
    stop_event = getattr(app.state, _STOP_ATTR, None)
    th = getattr(app.state, _THREAD_ATTR, None)
    if stop_event is not None:
        stop_event.set()
    if th is not None:
        try:
            th.join(timeout=5.0)
        except Exception:
            pass
