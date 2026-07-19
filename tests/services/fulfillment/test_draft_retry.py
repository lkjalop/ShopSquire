from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import draft_retry
from src.app.services.fulfillment.workflow import TransitionResult


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    return sessionmaker(bind=engine, future=True)()


def test_draft_retry_is_durable_and_marks_success(monkeypatch):
    db = _db()
    try:
        draft_retry.enqueue(
            db,
            case_id="case-1",
            item_ref="SKU-1",
            quantity=7,
            trace_id="trace-1",
            error=RuntimeError("first failure"),
        )
        db.commit()

        def _success(*args, **kwargs):
            return TransitionResult(True, "case-1", "QUOTE_DRAFTED", "ok"), {"content_hash": "h"}

        monkeypatch.setattr("src.app.services.fulfillment.draft.draft_and_record", _success)
        result = draft_retry.run_due(db)
        db.commit()

        assert result == {"claimed": 1, "succeeded": 1, "failed": 0, "dead": 0}
        assert draft_retry.status_for_case(db, "case-1")["status"] == "succeeded"
    finally:
        db.close()


def test_draft_retry_backs_off_and_stops_at_attempt_cap(monkeypatch):
    db = _db()
    try:
        draft_retry.enqueue(
            db,
            case_id="case-2",
            item_ref="SKU-2",
            quantity=3,
            trace_id=None,
            error=RuntimeError("first failure"),
        )
        db.commit()

        monkeypatch.setattr(
            "src.app.services.fulfillment.draft.draft_and_record",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("still failing")),
        )
        result = draft_retry.run_due(db, max_attempts=1)
        db.commit()

        assert result == {"claimed": 1, "succeeded": 0, "failed": 0, "dead": 1}
        status = draft_retry.status_for_case(db, "case-2")
        assert status["status"] == "dead"
        assert status["attempt_count"] == 1
    finally:
        db.close()
