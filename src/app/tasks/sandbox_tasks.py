from __future__ import annotations

import logging
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="sandbox.detonate",
    queue="security",
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def detonate(self, job: Dict[str, Any]) -> Dict[str, Any]:
    """Process a sandbox detonation job queued by sandbox_queue.queue_sandbox_detonation().

    Calls runtime_confirmation.confirm_runtime_evidence() with the supplied context,
    logs the result to the decision trace, and returns a result dict.

    Retried up to 2 times on transient failure (e.g., Ollama unavailable).
    """
    try:
        from src.app.services.sandbox_queue import process_sandbox_job
        return process_sandbox_job(job)
    except Exception as exc:
        logger.warning("sandbox_tasks.detonate failed (attempt %d): %s", self.request.retries + 1, exc)
        raise self.retry(exc=exc)
