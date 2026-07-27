"""Bounded asynchronous deep enrichment for persisted inbound email."""
from __future__ import annotations

import json

from sqlalchemy import text

from src.app.workers.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="src.app.tasks.email_enrichment_tasks.enrich_inbound_email",
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=90,
    time_limit=120,
)
def enrich_inbound_email(self, inbox_id: str, tenant_id: str) -> dict:
    from src.app.models.db import db_session
    from src.app.security.email_security import evaluate_email_security
    from src.app.services.inbound_email_evidence import load_raw_evidence

    try:
        with db_session() as db:
            row = db.execute(
                text(
                    "SELECT raw_evidence_ref FROM inbound_email_inbox "
                    "WHERE id=:id AND tenant_id=:tenant"
                ),
                {"id": inbox_id, "tenant": tenant_id},
            ).fetchone()
            if not row:
                return {"ok": False, "reason": "inbox_not_found"}
            db.execute(
                text(
                    "UPDATE inbound_email_inbox SET enrichment_status='running', "
                    "enrichment_attempts=enrichment_attempts+1 WHERE id=:id AND tenant_id=:tenant"
                ),
                {"id": inbox_id, "tenant": tenant_id},
            )
            email = load_raw_evidence(
                db,
                tenant_id=tenant_id,
                evidence_ref=str(row[0]),
                actor_id="email_enrichment_worker",
                purpose="bounded deep security enrichment",
                inbox_id=inbox_id,
            )
            verdict = evaluate_email_security(email, tenant_id=tenant_id)
            db.execute(
                text(
                    "UPDATE inbound_email_inbox SET enrichment_status='completed', "
                    "security_verdict_json=:verdict, enrichment_error=NULL, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=:id AND tenant_id=:tenant"
                ),
                {
                    "verdict": json.dumps(verdict, sort_keys=True, default=str),
                    "id": inbox_id,
                    "tenant": tenant_id,
                },
            )
            db.commit()
            return {"ok": True, "inbox_id": inbox_id}
    except Exception as exc:
        terminal = int(getattr(self.request, "retries", 0) or 0) >= int(self.max_retries or 3)
        try:
            with db_session() as db:
                db.execute(
                    text(
                        "UPDATE inbound_email_inbox SET enrichment_status=:status, "
                        "enrichment_error=:error, updated_at=CURRENT_TIMESTAMP "
                        "WHERE id=:id AND tenant_id=:tenant"
                    ),
                    {
                        "status": "dead_lettered" if terminal else "retrying",
                        "error": repr(exc)[:500],
                        "id": inbox_id,
                        "tenant": tenant_id,
                    },
                )
                db.commit()
        except Exception:
            pass
        if terminal:
            return {"ok": False, "inbox_id": inbox_id, "dead_lettered": True}
        raise self.retry(exc=exc)
