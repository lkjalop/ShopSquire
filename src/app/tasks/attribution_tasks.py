"""E3 — attribution reward feed (Celery).

Periodically turns SETTLED, attributed conversions into bandit rewards, fixing the bandit's
otherwise-undefined reward signal so the recommender learns from revenue rather than guesses.

DEFAULT-OFF: gated behind ATTRIBUTION_REWARD_FEED_ENABLED (default "0") until the quarantine
controls are bench-validated. Settled-order gate (ATTRIBUTION_SETTLE_DAYS, default 14) keeps a
burst of fresh/fake conversions from moving the model before the return window closes; the core
run_reward_feed adds idempotency + a per-uid cap. Errors are logged and isolated — never crash
the worker.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return str(os.getenv("ATTRIBUTION_REWARD_FEED_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@celery_app.task(name="src.app.tasks.attribution_tasks.attribution_reward_feed")
def attribution_reward_feed() -> Dict[str, Any]:
    if not _enabled():
        return {"skipped": "disabled"}
    try:
        settle_days = max(0, int(float(os.getenv("ATTRIBUTION_SETTLE_DAYS", "14") or 14)))
        per_uid_cap = max(1, int(float(os.getenv("ATTRIBUTION_REWARD_PER_UID_CAP", "50") or 50)))
        batch_limit = max(1, int(float(os.getenv("ATTRIBUTION_REWARD_BATCH_LIMIT", "500") or 500)))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=settle_days)).isoformat()
        from src.app.models.db import db_session
        from src.app.services.attribution import run_reward_feed
        with db_session() as db:
            summary = run_reward_feed(
                db,
                settle_cutoff_iso=cutoff,
                per_uid_cap=per_uid_cap,
                batch_limit=batch_limit,
            )
        logger.info("attribution_reward_feed summary=%s cutoff=%s", summary, cutoff)
        return summary
    except Exception as exc:  # never crash the scheduler — log + report
        logger.warning("attribution_reward_feed failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
