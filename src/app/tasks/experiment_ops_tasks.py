"""Experiment operations watchdog (Celery) — the safety net around the live rollback loop.

Periodically (a) FAIL-SAFE pauses live experiments if the eval loop itself has gone stale (its
heartbeat is older than EXPERIMENT_EVAL_MAX_STALE_SEC) so a nudge can't run unsupervised, and (b)
auto-reverts zombie experiments that have been 'live' past EXPERIMENT_MAX_LIVE_SEC. DEFAULT-OFF
(EXPERIMENT_WATCHDOG_ENABLED). Errors logged + isolated; never crash the worker.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return str(os.getenv("EXPERIMENT_WATCHDOG_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@celery_app.task(name="src.app.tasks.experiment_ops_tasks.experiment_watchdog")
def experiment_watchdog() -> Dict[str, Any]:
    if not _enabled():
        return {"skipped": "disabled"}
    try:
        max_stale = float(os.getenv("EXPERIMENT_EVAL_MAX_STALE_SEC", "3600") or 3600)
        max_live = float(os.getenv("EXPERIMENT_MAX_LIVE_SEC", str(14 * 24 * 3600)) or (14 * 24 * 3600))
        from src.app.models.db import db_session
        from src.app.services.experiment_ops import auto_revert_stale, pause_live_if_eval_stale
        with db_session() as db:
            from sqlalchemy import text
            tenants = [
                str(row[0]) for row in db.execute(
                    text("SELECT DISTINCT tenant_id FROM experiment_run "
                         "WHERE status='live' AND tenant_id IS NOT NULL")
                ).fetchall() if str(row[0] or "").strip()
            ]
            paused, zombies = [], []
            stale = False
            for tenant_id in tenants:
                health = pause_live_if_eval_stale(
                    db, tenant_id=tenant_id, max_age_seconds=max_stale
                )
                stale = stale or bool(health.get("stale"))
                paused.extend(health.get("paused") or [])
                zombies.extend(auto_revert_stale(
                    db, tenant_id=tenant_id, max_age_seconds=max_live
                ))
        logger.info("experiment_watchdog stale_paused=%s zombies_reverted=%s", paused, zombies)
        return {"eval_stale": stale, "paused": paused, "reverted_stale": zombies}
    except Exception as exc:
        logger.warning("experiment_watchdog failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
