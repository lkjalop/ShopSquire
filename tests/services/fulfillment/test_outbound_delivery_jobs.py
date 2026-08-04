from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.fulfillment import outbound_delivery, outbound_queue


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    db = Session(engine)
    db.execute(text(outbound_queue._DDL))
    db.execute(text("""
        CREATE TABLE outbound_delivery_job (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, status TEXT NOT NULL,
            requested_by TEXT NOT NULL, limit_count INTEGER NOT NULL,
            result_json TEXT, error TEXT, submitted_at TEXT NOT NULL,
            started_at TEXT, completed_at TEXT
        )
    """))
    db.commit()
    return db


def test_delivery_job_status_is_tenant_scoped():
    db = _db()
    outbound_delivery.create_job(
        db,
        job_id="job-1",
        tenant_id="tenant-a",
        requested_by="owner",
        limit=25,
    )
    assert outbound_delivery.job_status(
        db, job_id="job-1", tenant_id="tenant-a")["status"] == "queued"
    assert outbound_delivery.job_status(
        db, job_id="job-1", tenant_id="tenant-b") == {}

    outbound_delivery.mark_job_started(
        db, job_id="job-1", tenant_id="tenant-a")
    outbound_delivery.finish_job(
        db,
        job_id="job-1",
        tenant_id="tenant-a",
        result={"sent": 2},
    )
    completed = outbound_delivery.job_status(
        db, job_id="job-1", tenant_id="tenant-a")
    assert completed["status"] == "completed"
    assert completed["result"] == {"sent": 2}


def test_process_tenant_never_reads_another_tenant(monkeypatch):
    db = _db()
    seen = {}

    def _process(_db, *, tenant_id, limit):
        seen.update({"tenant_id": tenant_id, "limit": limit})
        return {"sent": 0, "sent_rows": []}

    monkeypatch.setattr(outbound_queue, "process_pending", _process)
    result = outbound_delivery.process_tenant(
        db, tenant_id="tenant-a", limit=500)
    assert seen == {"tenant_id": "tenant-a", "limit": 100}
    assert result["transitions"] == {"advanced": 0, "skipped": 0}


def test_process_tenant_fails_loudly_on_queue_error(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        outbound_queue,
        "process_pending",
        lambda *a, **k: {"sent": 0, "sent_rows": [], "error": "db_unavailable"},
    )
    try:
        outbound_delivery.process_tenant(db, tenant_id="tenant-a")
    except RuntimeError as exc:
        assert str(exc) == "db_unavailable"
    else:
        raise AssertionError("queue error must fail the durable job")
