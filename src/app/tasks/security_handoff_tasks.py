from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.workers.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="src.app.tasks.security_handoff_tasks.deliver_security_handoff",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=45,
    time_limit=60,
)
def deliver_security_handoff(self, event: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    from src.app.security.siem_adapter import emit_security_handoff

    return emit_security_handoff(dict(event or {}), force_inline=True)


@celery_app.task(
    bind=True,
    name="src.app.tasks.security_handoff_tasks.recover_due_security_handoffs",
    soft_time_limit=45,
    time_limit=55,
)
def recover_due_security_handoffs(self, limit: int = 100) -> dict[str, int]:  # noqa: ARG001
    """Resubmit unique due events after broker submission or worker interruption."""
    now = datetime.utcnow().isoformat()
    events: dict[str, dict[str, Any]] = {}
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, trace_id, decision_id, payload_json
                FROM security_handoff_attempts
                WHERE status IN ('queued','retrying')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                ORDER BY updated_at ASC LIMIT :limit
                """
            ),
            {"now": now, "limit": max(1, min(int(limit), 500))},
        ).fetchall()
    for row in rows:
        key = str(row[1] or row[2] or row[0])
        if key in events:
            continue
        try:
            payload = json.loads(str(row[3] or "{}"))
        except (TypeError, ValueError):
            payload = {}
        if payload:
            events[key] = payload
    for payload in events.values():
        deliver_security_handoff.delay(payload)
    return {"due_rows": len(rows), "events_resubmitted": len(events)}
