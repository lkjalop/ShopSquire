from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import set_engine
from src.app.models.orm import Base, RecommendationAuditOutboxRecord
from src.app.services.recommendation_audit_outbox import (
    enqueue_recommendation_audit,
    execute_recommendation_audit_job,
    recommendation_audit_outbox_metrics,
    recover_pending_recommendation_audits,
)
from src.app.services import recommendation_audit_outbox as audit_outbox


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


def test_terminal_failure_is_dead_lettered_and_visible_to_operator(monkeypatch):
    engine = _database()
    monkeypatch.setenv("RECOMMEND_AUDIT_MAX_ATTEMPTS", "1")
    monkeypatch.setattr(
        "src.app.workers.task_runner.submit_task", lambda *_args, **_kwargs: "task-audit",
    )
    queued = enqueue_recommendation_audit(
        tenant_id="portfolio", trace_id="trace-dead", payload=_payload("trace-dead"),
    )
    monkeypatch.setattr(
        "src.app.services.decision_log.log_decision",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("storage unavailable")),
    )
    execute_recommendation_audit_job({
        "outbox_id": queued["outbox_id"], "tenant_id": "portfolio",
    })
    with Session(engine) as db:
        health = recommendation_audit_outbox_metrics(db, tenant_id="portfolio")
    assert health["dead_letter_count"] == 1
    assert health["health"] == "degraded"
    assert health["oldest_pending_age_seconds"] == 0.0


def test_capacity_rejection_uses_cross_worker_redis_projection(monkeypatch):
    engine = _database()

    class FakeRedis:
        def __init__(self):
            self.values = {}

        def incr(self, key):
            self.values[key] = int(self.values.get(key, 0)) + 1
            return self.values[key]

        def get(self, key):
            return self.values.get(key)

    fake = FakeRedis()
    monkeypatch.setattr(audit_outbox, "_capacity_redis_client", lambda: fake)
    audit_outbox._record_capacity_rejection("portfolio")
    audit_outbox._record_capacity_rejection("portfolio")

    with Session(engine) as db:
        health = recommendation_audit_outbox_metrics(db, tenant_id="portfolio")
    assert health["capacity_rejection_count"] == 2
    assert health["capacity_rejection_metric_scope"] == "redis_cross_worker"


def test_capacity_rejection_labels_process_fallback(monkeypatch):
    engine = _database()
    monkeypatch.setattr(audit_outbox, "_capacity_redis_client", lambda: None)
    monkeypatch.setitem(audit_outbox._CAPACITY_REJECTIONS, "fallback", 4)
    with Session(engine) as db:
        health = recommendation_audit_outbox_metrics(db, tenant_id="fallback")
    assert health["capacity_rejection_count"] == 4
    assert health["capacity_rejection_metric_scope"] == "process_fallback"


def test_capacity_redis_recovers_after_bounded_retry(monkeypatch):
    class HealthyRedis:
        def ping(self):
            return True

    healthy = HealthyRedis()
    attempts = iter((None, healthy))
    clock = {"now": 100.0}
    monkeypatch.setenv("RECOMMEND_AUDIT_METRIC_REDIS_RETRY_SEC", "5")
    monkeypatch.setattr(audit_outbox.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        "src.app.services.redis_factory.create_redis_client",
        lambda **_kwargs: next(attempts),
    )
    monkeypatch.setattr(audit_outbox, "_CAPACITY_REDIS", None)
    monkeypatch.setattr(audit_outbox, "_CAPACITY_REDIS_INITIALIZED", False)
    monkeypatch.setattr(audit_outbox, "_CAPACITY_REDIS_RETRY_AFTER", 0.0)

    assert audit_outbox._capacity_redis_client() is None
    clock["now"] = 104.0
    assert audit_outbox._capacity_redis_client() is None
    clock["now"] = 105.0
    assert audit_outbox._capacity_redis_client() is healthy
