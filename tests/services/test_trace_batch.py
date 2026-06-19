"""Trace-event batching parity (latency #3b).

The batch must persist EXACTLY the same events as per-event writes — just in one bulk insert at
flush. Mid-request readers (the in-process cache) must still see events before flush. No event lost.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.decision_log import (
    begin_trace_batch,
    flush_trace_batch,
    get_cached_trace_events,
    log_trace_event,
)


@pytest.fixture(autouse=True)
def _no_skip_env(monkeypatch):
    monkeypatch.delenv("SKIP_OBSERVER_ENDPOINTS", raising=False)
    monkeypatch.delenv("TRACE_EVENT_OUTBOX_ENABLED", raising=False)


def _rows(trace_id: str) -> int:
    try:
        with db_session() as db:
            return int(db.execute(
                text("SELECT COUNT(*) FROM decision_trace_events WHERE trace_id = :t"),
                {"t": trace_id},
            ).scalar() or 0)
    except Exception:
        return -1


def _emit(trace_id: str, n: int) -> None:
    for i in range(n):
        log_trace_event(trace_id, "agent_process", "system", f"s{i}", "system", None, {"i": i})


def test_batch_buffers_then_bulk_inserts():
    tid = f"t-batch-{uuid.uuid4().hex[:8]}"
    tok = begin_trace_batch()
    _emit(tid, 3)
    # buffered: not yet in DB ...
    assert _rows(tid) == 0
    # ... but the in-process cache already has them (mid-request readers lose nothing)
    assert len(get_cached_trace_events(tid)) == 3
    assert flush_trace_batch(tok) == 3
    assert _rows(tid) == 3


def test_unbatched_writes_immediately():
    tid = f"t-nobatch-{uuid.uuid4().hex[:8]}"
    _emit(tid, 3)
    assert _rows(tid) == 3  # per-event immediate write (unchanged behaviour)


def test_batched_count_equals_unbatched_parity():
    a = f"t-a-{uuid.uuid4().hex[:8]}"
    _emit(a, 5)

    b = f"t-b-{uuid.uuid4().hex[:8]}"
    tok = begin_trace_batch()
    _emit(b, 5)
    flush_trace_batch(tok)

    assert _rows(a) == _rows(b) == 5  # same number of persisted events either way


def test_batch_resets_after_flush():
    tid = f"t-reset-{uuid.uuid4().hex[:8]}"
    tok = begin_trace_batch()
    _emit(tid, 1)
    flush_trace_batch(tok)
    # after flush the batch is closed → a subsequent event writes immediately
    tid2 = f"t-after-{uuid.uuid4().hex[:8]}"
    _emit(tid2, 1)
    assert _rows(tid2) == 1
