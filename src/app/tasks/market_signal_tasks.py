"""Market signal backfill (Celery) — the batch wiring for Module 1 producers.

Periodically normalizes recent orders / conversions / search events into the market_signal stream
(idempotent via dedup, so re-runs are safe). DEFAULT-OFF (MARKET_SIGNAL_BACKFILL_ENABLED) — pure
ingestion (no behaviour change), but gated to avoid surprise background load until turned on. Errors
are logged and isolated; never crash the worker.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return str(os.getenv("MARKET_SIGNAL_BACKFILL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@celery_app.task(name="src.app.tasks.market_signal_tasks.market_signal_backfill")
def market_signal_backfill() -> Dict[str, Any]:
    if not _enabled():
        return {"skipped": "disabled"}
    try:
        limit = max(1, int(float(os.getenv("MARKET_SIGNAL_BACKFILL_LIMIT", "1000") or 1000)))
        min_trust = max(0.0, min(1.0, float(os.getenv("MARKET_SIGNAL_MIN_TRUST", "0") or 0)))
        from src.app.models.db import db_session
        from src.app.services.market_signal_adapters import backfill_from_db
        with db_session() as db:
            counts = backfill_from_db(db, limit=limit, min_trust=min_trust)
        logger.info("market_signal_backfill counts=%s", counts)
        return counts
    except Exception as exc:
        logger.warning("market_signal_backfill failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
