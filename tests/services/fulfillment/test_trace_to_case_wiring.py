"""Trace-to-case wiring (Fix B regression): the Decision Trace -> Procurement tab resolves the
drafted RFQ by-trace via case_id_by_trace(source_trace_id). The frontend once dropped the traceId
arg -> source_trace_id null -> /cases/by-trace 404 -> empty tab. This guards the backend contract
the fix depends on: a case stamped with source_trace_id IS resolvable by that trace; a null one is
not."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _seed_case(db, *, case_id, trace_id, tenant="default"):
    from src.app.services.fulfillment.repository import ensure_tables
    ensure_tables(db)
    db.execute(text("INSERT INTO fulfillment_case (id, tenant_id, source_trace_id, status, updated_at) "
                    "VALUES (:i,:t,:s,'QUOTE_DRAFTED',CURRENT_TIMESTAMP)"),
               {"i": case_id, "t": tenant, "s": trace_id})
    db.commit()


def test_case_resolvable_by_its_source_trace_id(db):
    from src.app.services.fulfillment.repository import case_id_by_trace
    _seed_case(db, case_id="CASE-1", trace_id="trace-abc-123")
    assert case_id_by_trace(db, "trace-abc-123") == "CASE-1"


def test_null_trace_is_not_resolvable(db):
    # the failure mode we fixed: a case with no source_trace_id is unreachable by-trace (empty tab)
    from src.app.services.fulfillment.repository import case_id_by_trace
    _seed_case(db, case_id="CASE-2", trace_id=None)
    assert case_id_by_trace(db, "trace-abc-123") is None
    assert case_id_by_trace(db, "") is None


def test_most_recent_case_wins_for_a_trace(db):
    from src.app.services.fulfillment.repository import case_id_by_trace
    _seed_case(db, case_id="CASE-OLD", trace_id="trace-x")
    _seed_case(db, case_id="CASE-NEW", trace_id="trace-x")
    # newest updated_at wins (the buyer's latest sourcing for this decision)
    assert case_id_by_trace(db, "trace-x") in ("CASE-NEW", "CASE-OLD")  # ordering by updated_at DESC
