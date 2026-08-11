from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.security import supplier_baseline


def test_supplier_baseline_event_always_has_a_cross_dialect_identity(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @contextmanager
    def session_scope():
        with Session(engine, future=True) as db:
            yield db

    monkeypatch.setattr(supplier_baseline, "db_session", session_scope)

    supplier_baseline.record_email_event(
        tenant_id="tenant-a",
        sender_domain="supplier.example",
        event_datetime="2026-08-05T10:00:00+00:00",
    )

    with Session(engine, future=True) as db:
        row = db.execute(text(
            "SELECT id,tenant_id,sender_domain_hash FROM supplier_baseline_events"
        )).one()
    assert isinstance(row[0], int)
    assert row[0] > 0
    assert row[1] == "tenant-a"
    assert row[2] != "supplier.example"
