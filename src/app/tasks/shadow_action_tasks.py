"""Shadow-action generation (Celery) — propose typed actions from findings; LOG ONLY.

Periodically reads persisted M3 findings and logs typed action proposals (adjust_ranking,
suppress_low_stock, revise_support_copy) WITHOUT executing any of them — the observability layer that
shows what the autonomous system WOULD do before it is ever allowed to act. DEFAULT-OFF
(SHADOW_ACTIONS_ENABLED). Even when enabled it only writes proposal rows + a trace event; promotion to
a real (reversible, experiment-gated) action is a separate, deliberate step. Never crashes the worker.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return str(os.getenv("SHADOW_ACTIONS_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@celery_app.task(name="src.app.tasks.shadow_action_tasks.generate_shadow_actions")
def generate_shadow_actions() -> Dict[str, Any]:
    if not _enabled():
        return {"skipped": "disabled"}
    try:
        from src.app.models.db import db_session
        from src.app.services.shadow_actions import generate_shadow_actions as _generate
        with db_session() as db:
            result = _generate(db)
            db.commit()
        logger.info("generate_shadow_actions %s (executed=0 — log-only)", result)
        return result
    except Exception as exc:
        logger.warning("generate_shadow_actions failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
