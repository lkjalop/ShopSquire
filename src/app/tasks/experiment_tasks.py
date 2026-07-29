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
        from src.app.models.db import db_session
        from src.app.services.experiment_eval import evaluate_live_experiments, returns_guardrail
        from src.app.services.experiment_ops import (
            composite_guardrail,
            escalation_rate_guardrail,
            record_heartbeat,
        )
        # Broader guardrails: returns AND escalation-rate (anti-Goodhart is multi-dimensional, not
        # just refunds). Either breaching reverts the treatment.
        guardrail = composite_guardrail(returns_guardrail, escalation_rate_guardrail)
        with db_session() as db:
            from sqlalchemy import text
            tenants = [
                str(row[0]) for row in db.execute(
                    text("SELECT DISTINCT tenant_id FROM experiment_run "
                         "WHERE status='live' AND tenant_id IS NOT NULL")
                ).fetchall() if str(row[0] or "").strip()
            ]
            outcomes = []
            for tenant_id in tenants:
                outcomes.extend(evaluate_live_experiments(
                    db, tenant_id=tenant_id, guardrail_fn=guardrail
                ))
            record_heartbeat(db)  # stamp the safety loop's liveness (worker-health watchdog reads it)
            db.commit()
        reverted = [o.get("experiment_id") for o in outcomes if o.get("reverted")]
        logger.info("evaluate_experiments outcomes=%d reverted=%s", len(outcomes), reverted)
        return {"evaluated": len(outcomes), "reverted": reverted}
    except Exception as exc:
        logger.warning("evaluate_experiments failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
