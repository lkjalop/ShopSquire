"""Scheduled data-retention sweep (Celery beat). Storage-limitation half of compliance — UNIFORM, never
IP/geo gated. See services/retention_sweeper.py + config/retention_policy.json."""
from __future__ import annotations

import logging

from src.app.workers.celery_app import celery_app

_log = logging.getLogger("shopsquire.retention")


@celery_app.task(name="src.app.tasks.retention_tasks.run_retention_sweep")
def run_retention_sweep() -> dict:
    """Age out abandoned ephemeral state (idle carts, stale conversation, TTL-less Redis session keys)."""
    from src.app.services.retention_sweeper import sweep_now
    report = sweep_now(dry_run=False)
    try:
        from src.app.models.db import db_session
        from src.app.services.inbound_email_evidence import purge_expired_evidence

        with db_session() as db:
            report["inbound_email_evidence_purged"] = purge_expired_evidence(
                db,
                actor_id="retention_worker",
                purpose="scheduled retention policy enforcement",
            )
            db.commit()
    except Exception as exc:
        report["inbound_email_evidence_purge_error"] = repr(exc)[:300]
    _log.info(
        "retention sweep: carts_soft=%s carts_hard=%s chat=%s redis=%s",
        report.get("carts_soft_expired"), report.get("carts_hard_purged"),
        report.get("chat_messages_purged"), report.get("session_keys_expiring"),
    )
    return report
