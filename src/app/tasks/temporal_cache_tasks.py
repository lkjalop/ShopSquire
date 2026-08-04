"""Celery entry point for tenant-scoped temporal cache rebuilds."""
from __future__ import annotations

import os

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


@celery_app.task(
    name="src.app.tasks.temporal_cache_tasks.evict_superseded_cache_entry",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=8,
)
def evict_superseded_cache_entry(tenant_id: str, job_id: str) -> dict:
    from src.app.services.semantic_cache import SemanticCache
    from src.app.services.temporal_invalidation import execute_cache_eviction

    cache = SemanticCache(redis_url=os.getenv("REDIS_URL"))
    if not cache.is_shared_backend:
        raise RuntimeError("shared_cache_backend_unavailable")
    with db_session() as db:
        result = execute_cache_eviction(db, tenant_id=tenant_id, job_id=job_id, cache=cache)
        db.commit()
        if result.get("status") == "degraded":
            raise RuntimeError(str(result.get("error") or "cache_eviction_failed"))
        return result


@celery_app.task(
    name="src.app.tasks.temporal_cache_tasks.dispatch_temporal_cache_evictions",
    acks_late=True,
    reject_on_worker_lost=True,
)
def dispatch_temporal_cache_evictions(limit: int = 50) -> dict:
    from src.app.services.temporal_invalidation import dispatch_queued_evictions

    def dispatch(tenant_id: str, job_id: str) -> None:
        evict_superseded_cache_entry.delay(tenant_id=tenant_id, job_id=job_id)

    with db_session() as db:
        result = dispatch_queued_evictions(db, dispatch=dispatch, limit=limit)
        db.commit()
        return result
