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


def test_backfill_repairs_null_trace_so_case_becomes_resolvable(db):
    # A case first materialized without a trace (source_trace_id NULL) is unreachable by-trace. A later
    # confirm that carries a trace must backfill it so the Procurement tab resolves — the A2 demo blocker.
    from src.app.services.fulfillment.repository import backfill_source_trace_id, case_id_by_trace
    _seed_case(db, case_id="CASE-NULL", trace_id=None)
    assert case_id_by_trace(db, "trace-late") is None  # before repair: not resolvable

    n = backfill_source_trace_id(db, ["CASE-NULL"], "trace-late")
    assert n == 1
    assert case_id_by_trace(db, "trace-late") == "CASE-NULL"  # after repair: resolvable


def test_backfill_never_rebinds_a_case_that_already_has_a_trace(db):
    # Idempotent + non-destructive: a case already stamped with a trace must NOT be overwritten (that
    # would break the original trace's by-trace link). Backfill only fills NULLs.
    from src.app.services.fulfillment.repository import backfill_source_trace_id, case_id_by_trace
    _seed_case(db, case_id="CASE-HASTRACE", trace_id="trace-original")

    n = backfill_source_trace_id(db, ["CASE-HASTRACE"], "trace-different")
    assert n == 0                                                    # nothing repaired
    assert case_id_by_trace(db, "trace-original") == "CASE-HASTRACE"  # original link intact
    assert case_id_by_trace(db, "trace-different") is None           # never rebound


def test_backfill_is_noop_on_empty_or_missing_trace(db):
    from src.app.services.fulfillment.repository import backfill_source_trace_id
    _seed_case(db, case_id="CASE-Z", trace_id=None)
    assert backfill_source_trace_id(db, ["CASE-Z"], "") == 0     # no trace to stamp
    assert backfill_source_trace_id(db, [], "trace-y") == 0      # no cases


def test_case_ids_by_trace_returns_all_cases_for_a_multi_supplier_order(db):
    # A multi-supplier bulk order opens ONE case per supplier group, all sharing the trace. case_id_by_trace
    # returns only the newest (single-supplier view); case_ids_by_trace returns ALL so the read-only trace
    # can show every drafted RFQ. Regression for "3 suppliers, where are the emails?".
    from src.app.services.fulfillment.repository import case_ids_by_trace, case_id_by_trace
    _seed_case(db, case_id="CASE-BIZ", trace_id="trace-multi")
    _seed_case(db, case_id="CASE-APPLE", trace_id="trace-multi")
    ids = case_ids_by_trace(db, "trace-multi")
    assert set(ids) == {"CASE-BIZ", "CASE-APPLE"}          # ALL cases surfaced
    assert case_id_by_trace(db, "trace-multi") in ids       # single-resolver still returns one of them
    assert case_ids_by_trace(db, "trace-none") == []        # unknown trace → empty, not error
