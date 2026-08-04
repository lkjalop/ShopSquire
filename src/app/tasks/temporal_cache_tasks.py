"""Celery entry point for tenant-scoped temporal cache rebuilds."""
from __future__ import annotations

from src.app.models.db import db_session
from src.app.workers.celery_app import celery_app


@celery_app.task(
    name="src.app.tasks.temporal_cache_tasks.rebuild_temporal_cache_entry",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def rebuild_temporal_cache_entry(tenant_id: str, job_id: str) -> dict:
    from src.app.services.temporal_cache_rebuild import execute_cache_rebuild

    with db_session() as db:
        result = execute_cache_rebuild(db, tenant_id=tenant_id, job_id=job_id)
        db.commit()
        return result


@celery_app.task(
    name="src.app.tasks.temporal_cache_tasks.dispatch_temporal_cache_rebuilds",
    acks_late=True,
    reject_on_worker_lost=True,
)
def dispatch_temporal_cache_rebuilds(limit: int = 50) -> dict:
    """Sweep only already-committed jobs; duplicate delivery is harmless."""
    from src.app.services.temporal_cache_rebuild import dispatch_queued_rebuilds

    def dispatch(tenant_id: str, job_id: str) -> None:
        rebuild_temporal_cache_entry.delay(tenant_id=tenant_id, job_id=job_id)

    with db_session() as db:
        result = dispatch_queued_rebuilds(db, dispatch=dispatch, limit=limit)
        db.commit()
        return result
