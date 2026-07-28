"""Background maintenance for the fulfillment domain."""
from __future__ import annotations

import os
import uuid

from src.app.models.db import db_session
from src.app.workers.celery_app import celery_app


@celery_app.task(name="src.app.tasks.fulfillment_tasks.retry_supplier_drafts")
def retry_supplier_drafts(limit: int = 20) -> dict:
    from src.app.services.fulfillment.draft_retry import run_due
    with db_session() as db:
        out = run_due(db, limit=limit)
        db.commit()
        return out


@celery_app.task(
    bind=True,
    name="src.app.tasks.fulfillment_tasks.process_outbound_delivery",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def process_outbound_delivery(
    self,
    tenant_id: str,
    job_id: str,
    limit: int = 50,
) -> dict:
    """Deliver one bounded tenant batch and persist observable job state."""
    from src.app.services.fulfillment import outbound_delivery

    with db_session() as db:
        outbound_delivery.mark_job_started(
            db,
            job_id=job_id,
            tenant_id=tenant_id,
        )
    try:
        with db_session() as db:
            result = outbound_delivery.process_tenant(
                db,
                tenant_id=tenant_id,
                limit=limit,
            )
        with db_session() as db:
            outbound_delivery.finish_job(
                db,
                job_id=job_id,
                tenant_id=tenant_id,
                result=result,
            )
        return result
    except Exception as exc:
        with db_session() as db:
            outbound_delivery.finish_job(
                db,
                job_id=job_id,
                tenant_id=tenant_id,
                error=f"{type(exc).__name__}: {exc}",
            )
        raise


def _outbound_tenant_ids() -> tuple[str, ...]:
    configured = tuple(
        dict.fromkeys(
            value.strip()
            for value in os.getenv("OUTBOUND_DELIVERY_TENANTS", "").split(",")
            if value.strip()
        )
    )
    if configured:
        return configured[:100]
    from src.app.platform.tenant_registry import registered_tenant_ids
    return registered_tenant_ids()[:100]


@celery_app.task(
    name="src.app.tasks.fulfillment_tasks.sweep_outbound_delivery",
    acks_late=True,
    reject_on_worker_lost=True,
)
def sweep_outbound_delivery(limit: int = 50) -> dict:
    """Periodically drive due retries for every authoritative tenant."""
    from src.app.services.fulfillment import outbound_delivery

    reports = {}
    for tenant_id in _outbound_tenant_ids():
        job_id = f"outjob-{uuid.uuid4().hex}"
        try:
            with db_session() as db:
                outbound_delivery.create_job(
                    db,
                    job_id=job_id,
                    tenant_id=tenant_id,
                    requested_by="celery_beat",
                    limit=limit,
                )
                outbound_delivery.mark_job_started(
                    db,
                    job_id=job_id,
                    tenant_id=tenant_id,
                )
            with db_session() as db:
                result = outbound_delivery.process_tenant(
                    db,
                    tenant_id=tenant_id,
                    limit=limit,
                )
            with db_session() as db:
                outbound_delivery.finish_job(
                    db,
                    job_id=job_id,
                    tenant_id=tenant_id,
                    result=result,
                )
            reports[tenant_id] = result
        except Exception as exc:
            with db_session() as db:
                outbound_delivery.finish_job(
                    db,
                    job_id=job_id,
                    tenant_id=tenant_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            reports[tenant_id] = {"error": f"{type(exc).__name__}: {exc}"}
    return {"tenants": reports}
