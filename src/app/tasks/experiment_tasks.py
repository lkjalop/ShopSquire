"""Experiment evaluation (Celery) — the autonomous rollback cadence.

Periodically evaluates every LIVE experiment and auto-reverts losers / guardrail-breachers, so a live
ranking nudge that doesn't earn its keep (or hurts a guardrail) stops itself. DEFAULT-OFF
(EXPERIMENT_EVAL_ENABLED). Errors logged + isolated; never crash the worker.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return str(os.getenv("EXPERIMENT_EVAL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@celery_app.task(name="src.app.tasks.experiment_tasks.evaluate_experiments")
def evaluate_experiments() -> Dict[str, Any]:
    if not _enabled():
        return {"skipped": "disabled"}
    try:
        min_samples = max(2, int(float(os.getenv("EXPERIMENT_EVAL_MIN_SAMPLES", "30") or 30)))
        from src.app.models.db import db_session
        from src.app.services.experiment_eval import evaluate_live_experiments
        with db_session() as db:
            outcomes = evaluate_live_experiments(db, min_samples=min_samples)
        reverted = [o.get("experiment_id") for o in outcomes if o.get("reverted")]
        logger.info("evaluate_experiments outcomes=%d reverted=%s", len(outcomes), reverted)
        return {"evaluated": len(outcomes), "reverted": reverted}
    except Exception as exc:
        logger.warning("evaluate_experiments failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
