"""Human-feedback backfill (Celery) — batch derivation of human-in-the-loop learning signals.

Periodically derives feedback rows from tables that already hold the judgement (returns →
refunded/chargebacked orders; finding corrections → human-corrected market findings) into the
human_feedback envelope (idempotent via dedup). The event-driven types (approval / rejection /
nqe_correction / escalation) arrive directly via human_feedback.record_feedback() at their call
sites. DEFAULT-OFF (HUMAN_FEEDBACK_BACKFILL_ENABLED). Errors logged + isolated; never crash the worker.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return str(os.getenv("HUMAN_FEEDBACK_BACKFILL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@celery_app.task(name="src.app.tasks.human_feedback_tasks.human_feedback_backfill")
def human_feedback_backfill() -> Dict[str, Any]:
    if not _enabled():
        return {"skipped": "disabled"}
    try:
        limit = max(1, int(float(os.getenv("HUMAN_FEEDBACK_BACKFILL_LIMIT", "1000") or 1000)))
        from src.app.models.db import db_session
        from src.app.services.human_feedback import backfill_from_db
        with db_session() as db:
            counts = backfill_from_db(db, limit=limit)
        logger.info("human_feedback_backfill counts=%s", counts)
        return counts
    except Exception as exc:
        logger.warning("human_feedback_backfill failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
