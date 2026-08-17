"""Durable, bounded hand-off for recommendation decision persistence."""
from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update

from src.app.models.orm import RecommendationAuditOutboxRecord


_METRIC_LOCK = threading.Lock()
_CAPACITY_REJECTIONS: dict[str, int] = {}
_CAPACITY_REDIS: Any | None = None
_CAPACITY_REDIS_INITIALIZED = False
_CAPACITY_REDIS_RETRY_AFTER = 0.0
_CAPACITY_METRIC_PREFIX = "shopsquire:recommendation_audit:capacity_rejections:v1"


def _capacity_redis_client() -> Any | None:
    """Return a fail-fast Redis client once, without making Redis authoritative.

    Redis provides the cross-worker aggregate. The process counter remains an
    explicitly labelled fallback for local/degraded profiles.
    """
    global _CAPACITY_REDIS, _CAPACITY_REDIS_INITIALIZED, _CAPACITY_REDIS_RETRY_AFTER
    now = time.monotonic()
    with _METRIC_LOCK:
        if _CAPACITY_REDIS is not None:
            return _CAPACITY_REDIS
        if _CAPACITY_REDIS_INITIALIZED and now < _CAPACITY_REDIS_RETRY_AFTER:
            return None
        _CAPACITY_REDIS_INITIALIZED = True
        try:
            from src.app.services.redis_factory import create_redis_client

            candidate = create_redis_client(connect_timeout=0.05, socket_timeout=0.1)
            if candidate is not None:
                candidate.ping()
                _CAPACITY_REDIS = candidate
        except Exception:
            _CAPACITY_REDIS = None
        if _CAPACITY_REDIS is None:
            try:
                retry_seconds = max(1.0, min(float(os.getenv(
                    "RECOMMEND_AUDIT_METRIC_REDIS_RETRY_SEC", "30",
                )), 300.0))
            except (TypeError, ValueError):
                retry_seconds = 30.0
            _CAPACITY_REDIS_RETRY_AFTER = now + retry_seconds
        return _CAPACITY_REDIS


def _mark_capacity_redis_failed(redis_client: Any) -> None:
    global _CAPACITY_REDIS, _CAPACITY_REDIS_RETRY_AFTER
    with _METRIC_LOCK:
        if _CAPACITY_REDIS is redis_client:
            _CAPACITY_REDIS = None
            try:
                retry_seconds = max(1.0, min(float(os.getenv(
                    "RECOMMEND_AUDIT_METRIC_REDIS_RETRY_SEC", "30",
                )), 300.0))
            except (TypeError, ValueError):
                retry_seconds = 30.0
            _CAPACITY_REDIS_RETRY_AFTER = time.monotonic() + retry_seconds


def _capacity_key(tenant_id: str) -> str:
    tenant_hash = hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()[:20]
    return f"{_CAPACITY_METRIC_PREFIX}:{tenant_hash}"


def _record_capacity_rejection(tenant_id: str) -> None:
    with _METRIC_LOCK:
        _CAPACITY_REJECTIONS[tenant_id] = _CAPACITY_REJECTIONS.get(tenant_id, 0) + 1
    try:
        from src.app.observability.pilot_runtime_metrics import (
            recommendation_audit_capacity_rejections_total,
        )

        recommendation_audit_capacity_rejections_total.inc()
    except Exception:
        pass
    redis_client = _capacity_redis_client()
    if redis_client is not None:
        try:
            redis_client.incr(_capacity_key(tenant_id))
        except Exception:
            # The local counter remains truthful for this process. Do not call
            # the aggregate cross-worker value authoritative after Redis fails.
            _mark_capacity_redis_failed(redis_client)


def _capacity_rejection_projection(tenant_id: str) -> tuple[int, str]:
    redis_client = _capacity_redis_client()
    if redis_client is not None:
        try:
            return int(redis_client.get(_capacity_key(tenant_id)) or 0), "redis_cross_worker"
        except Exception:
            _mark_capacity_redis_failed(redis_client)
    with _METRIC_LOCK:
        return int(_CAPACITY_REJECTIONS.get(tenant_id, 0)), "process_fallback"


def _max_attempts() -> int:
    try:
        return max(1, min(int(os.getenv("RECOMMEND_AUDIT_MAX_ATTEMPTS", "3")), 20))
    except (TypeError, ValueError):
        return 3


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
            _record_capacity_rejection(tenant_id)
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
            current = db.execute(select(RecommendationAuditOutboxRecord).where(
                RecommendationAuditOutboxRecord.outbox_id == outbox_id,
            )).scalar_one()
            terminal = int(current.attempts or 0) >= _max_attempts()
            db.execute(update(RecommendationAuditOutboxRecord).where(
                RecommendationAuditOutboxRecord.outbox_id == outbox_id,
                RecommendationAuditOutboxRecord.status == "running",
            ).values(
                status="dead_letter" if terminal else "retry",
                error_code=type(exc).__name__, updated_at=_now(),
            ))
            db.commit()
        if terminal:
            return
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


def recommendation_audit_outbox_metrics(
    db, *, tenant_id: str, now: datetime | None = None,
) -> dict[str, Any]:
    """Operator projection; absence and terminal failure are never collapsed."""

    stamp = now or _now()
    rows = db.execute(select(RecommendationAuditOutboxRecord).where(
        RecommendationAuditOutboxRecord.tenant_id == tenant_id,
    )).scalars().all()
    statuses = {
        name: sum(1 for row in rows if row.status == name)
        for name in (
            "queued", "running", "retry", "enqueue_degraded", "completed", "dead_letter",
        )
    }
    pending = [row for row in rows if row.status in {
        "queued", "running", "retry", "enqueue_degraded",
    }]
    oldest_age = max(
        (max(0.0, (stamp - row.created_at.replace(
            tzinfo=row.created_at.tzinfo or timezone.utc,
        )).total_seconds()) for row in pending),
        default=0.0,
    )
    rejected, rejection_metric_scope = _capacity_rejection_projection(tenant_id)
    return {
        "schema_version": "recommendation-audit-outbox-health-v1",
        "tenant_id": tenant_id,
        "status_counts": statuses,
        "pending_count": len(pending),
        "oldest_pending_age_seconds": round(oldest_age, 3),
        "retry_attempt_count": sum(int(row.attempts or 0) for row in rows if row.status == "retry"),
        "capacity_rejection_count": rejected,
        "capacity_rejection_metric_scope": rejection_metric_scope,
        "dead_letter_count": statuses["dead_letter"],
        "health": "degraded" if statuses["dead_letter"] or statuses["enqueue_degraded"] else "healthy",
        "authority": "operator_observability_only",
        "observed_at": stamp.isoformat(),
    }


__all__ = [
    "enqueue_recommendation_audit", "execute_recommendation_audit_job",
    "recover_pending_recommendation_audits", "register_recommendation_audit_handler",
    "recommendation_audit_outbox_metrics",
]
