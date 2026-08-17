"""Durable, bounded hand-off for recommendation decision persistence."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update

from src.app.models.orm import RecommendationAuditOutboxRecord


TASK_NAME = "recommendation_audit_persist"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_capacity() -> int:
    try:
        configured = int(os.getenv("RECOMMEND_AUDIT_OUTBOX_MAX", "10000"))
    except (TypeError, ValueError):
        configured = 10_000
    return max(100, min(configured, 100_000))


def _outbox_id(tenant_id: str, trace_id: str) -> str:
    return "rao-" + hashlib.sha256(
        f"{tenant_id}\x1f{trace_id}".encode("utf-8")
    ).hexdigest()[:24]


def enqueue_recommendation_audit(
    *, tenant_id: str, trace_id: str, payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist one bounded item before dispatching it to the worker."""

    from src.app.models.db import db_session
    from src.app.workers.task_runner import submit_task

    maximum = _bounded_capacity()
    outbox_id = _outbox_id(tenant_id, trace_id)
    with db_session() as db:
        existing = db.execute(select(RecommendationAuditOutboxRecord).where(
            RecommendationAuditOutboxRecord.outbox_id == outbox_id,
        )).scalar_one_or_none()
        if existing is not None:
            return {
                "outbox_id": existing.outbox_id, "status": existing.status,
                "task_id": existing.task_id, "durable": True,
            }
        pending = int(db.execute(select(func.count()).select_from(
            RecommendationAuditOutboxRecord
        ).where(RecommendationAuditOutboxRecord.status.in_((
            "queued", "running", "retry", "enqueue_degraded",
        )))).scalar() or 0)
        if pending >= maximum:
            return {
                "outbox_id": None, "status": "capacity_rejected",
                "task_id": None, "durable": False,
            }
        stamp = _now()
        record = RecommendationAuditOutboxRecord(
            outbox_id=outbox_id, tenant_id=tenant_id, trace_id=trace_id,
            status="queued", payload_json=payload, attempts=0,
            created_at=stamp, updated_at=stamp,
        )
        db.add(record)
        db.commit()
        try:
            record.task_id = submit_task(TASK_NAME, {
                "outbox_id": outbox_id, "tenant_id": tenant_id,
            })
            record.updated_at = _now()
            db.commit()
        except RuntimeError as exc:
            record.status = "enqueue_degraded"
            record.error_code = str(exc)[:120]
            record.updated_at = _now()
            db.commit()
        db.refresh(record)
        return {
            "outbox_id": outbox_id, "status": record.status,
            "task_id": record.task_id, "durable": True,
        }


def execute_recommendation_audit_job(payload: dict[str, Any]) -> None:
    from src.app.models.db import db_session
    from src.app.services.decision_log import log_decision

    outbox_id = str(payload.get("outbox_id") or "")
    tenant_id = str(payload.get("tenant_id") or "")
    if not outbox_id or not tenant_id:
        raise ValueError("recommendation_audit_identity_required")
    with db_session() as db:
        claimed = db.execute(update(RecommendationAuditOutboxRecord).where(
            RecommendationAuditOutboxRecord.outbox_id == outbox_id,
            RecommendationAuditOutboxRecord.tenant_id == tenant_id,
            RecommendationAuditOutboxRecord.status.in_((
                "queued", "retry", "enqueue_degraded",
            )),
        ).values(
            status="running",
            attempts=RecommendationAuditOutboxRecord.attempts + 1,
            updated_at=_now(), error_code=None,
        ))
        if int(claimed.rowcount or 0) != 1:
            db.rollback()
            return
        db.commit()
        record = db.execute(select(RecommendationAuditOutboxRecord).where(
            RecommendationAuditOutboxRecord.outbox_id == outbox_id,
        )).scalar_one()
        decision_payload = dict(record.payload_json or {})

    try:
        persisted = log_decision(**decision_payload)
        if not persisted:
            raise RuntimeError("recommendation_decision_not_persisted")
    except Exception as exc:
        with db_session() as db:
            db.execute(update(RecommendationAuditOutboxRecord).where(
                RecommendationAuditOutboxRecord.outbox_id == outbox_id,
                RecommendationAuditOutboxRecord.status == "running",
            ).values(status="retry", error_code=type(exc).__name__, updated_at=_now()))
            db.commit()
        raise

    with db_session() as db:
        db.execute(update(RecommendationAuditOutboxRecord).where(
            RecommendationAuditOutboxRecord.outbox_id == outbox_id,
            RecommendationAuditOutboxRecord.status == "running",
        ).values(status="completed", completed_at=_now(), updated_at=_now()))
        db.commit()


def recover_pending_recommendation_audits(*, limit: int = 100) -> int:
    """Resubmit durable pending rows after a process restart."""

    from src.app.models.db import db_session
    from src.app.workers.task_runner import submit_task

    with db_session() as db:
        try:
            stale_after = max(30, min(int(os.getenv(
                "RECOMMEND_AUDIT_RUNNING_STALE_SEC", "300",
            )), 3600))
        except (TypeError, ValueError):
            stale_after = 300
        db.execute(update(RecommendationAuditOutboxRecord).where(
            RecommendationAuditOutboxRecord.status == "running",
            RecommendationAuditOutboxRecord.updated_at < _now() - timedelta(seconds=stale_after),
        ).values(
            status="retry", error_code="stale_running_reclaimed", updated_at=_now(),
        ))
        db.commit()
        rows = db.execute(select(RecommendationAuditOutboxRecord).where(
            RecommendationAuditOutboxRecord.status.in_((
                "queued", "retry", "enqueue_degraded",
            )),
        ).order_by(RecommendationAuditOutboxRecord.created_at.asc()).limit(limit)).scalars().all()
        identities = [(row.outbox_id, row.tenant_id) for row in rows]
    submitted = 0
    for outbox_id, tenant_id in identities:
        try:
            submit_task(TASK_NAME, {"outbox_id": outbox_id, "tenant_id": tenant_id})
            submitted += 1
        except RuntimeError:
            break
    return submitted


def register_recommendation_audit_handler() -> None:
    from src.app.workers.task_runner import register_handler

    register_handler(TASK_NAME, execute_recommendation_audit_job)


__all__ = [
    "enqueue_recommendation_audit", "execute_recommendation_audit_job",
    "recover_pending_recommendation_audits", "register_recommendation_audit_handler",
]
