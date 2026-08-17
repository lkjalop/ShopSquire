from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import set_engine
from src.app.models.orm import Base, RecommendationAuditOutboxRecord
from src.app.services.recommendation_audit_outbox import (
    enqueue_recommendation_audit,
    execute_recommendation_audit_job,
    recover_pending_recommendation_audits,
)


def _database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    set_engine(engine)
    return engine


def _payload(trace_id: str) -> dict:
    return {
        "agent_name": "Recommendation_Core",
        "input_data": {"query": "test"},
        "retrieved_context": {},
        "proposed_action": {"decision_mode": "no_action"},
        "decision_id": trace_id,
        "tenant_id": "portfolio",
        "event_type": "recommendation_result",
    }


def test_audit_outbox_persists_before_worker_and_completes(monkeypatch):
    engine = _database()
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-audit",
    )
    queued = enqueue_recommendation_audit(
        tenant_id="portfolio", trace_id="trace-1", payload=_payload("trace-1"),
    )
    assert queued == {
        "outbox_id": queued["outbox_id"], "status": "queued",
        "task_id": "task-audit", "durable": True,
    }
    monkeypatch.setattr(
        "src.app.services.decision_log.log_decision", lambda **_kwargs: "trace-1",
    )
    execute_recommendation_audit_job({
        "outbox_id": queued["outbox_id"], "tenant_id": "portfolio",
    })
    with Session(engine) as db:
        stored = db.execute(select(RecommendationAuditOutboxRecord)).scalar_one()
    assert stored.status == "completed"
    assert stored.attempts == 1


def test_audit_outbox_is_idempotent_per_tenant_trace(monkeypatch):
    _database()
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-audit",
    )
    first = enqueue_recommendation_audit(
        tenant_id="portfolio", trace_id="trace-2", payload=_payload("trace-2"),
    )
    second = enqueue_recommendation_audit(
        tenant_id="portfolio", trace_id="trace-2", payload=_payload("trace-2"),
    )
    assert second["outbox_id"] == first["outbox_id"]


def test_restart_reclaims_stale_running_audit(monkeypatch):
    engine = _database()
    monkeypatch.setenv("RECOMMEND_AUDIT_RUNNING_STALE_SEC", "30")
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-audit",
    )
    enqueue_recommendation_audit(
        tenant_id="portfolio", trace_id="trace-stale", payload=_payload("trace-stale"),
    )
    with Session(engine) as db:
        record = db.execute(select(RecommendationAuditOutboxRecord)).scalar_one()
        record.status = "running"
        record.updated_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.commit()
    assert recover_pending_recommendation_audits() == 1
    with Session(engine) as db:
        record = db.execute(select(RecommendationAuditOutboxRecord)).scalar_one()
    assert record.status == "retry"
    assert record.error_code == "stale_running_reclaimed"
