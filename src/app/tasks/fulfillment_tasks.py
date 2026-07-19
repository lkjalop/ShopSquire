"""Background maintenance for the fulfillment domain."""
from __future__ import annotations

from src.app.models.db import db_session
from src.app.workers.celery_app import celery_app


@celery_app.task(name="src.app.tasks.fulfillment_tasks.retry_supplier_drafts")
def retry_supplier_drafts(limit: int = 20) -> dict:
    from src.app.services.fulfillment.draft_retry import run_due
    with db_session() as db:
        out = run_due(db, limit=limit)
        db.commit()
        return out
