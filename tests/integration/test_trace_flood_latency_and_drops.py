import asyncio
import time


def test_trace_flood_is_bounded_and_drops(monkeypatch):
    from src.app.services import decision_log
    from src.app.services import trace_broker

    # Don't let this test depend on DB throughput; we are testing broker backpressure behavior.
    class _NoopSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(decision_log, "db_session", lambda: _NoopSession())
    try:
        import src.app.models.decision_trace_events as dte

        monkeypatch.setattr(dte, "ensure_decision_trace_events_table", lambda: None)
    except Exception:
        pass

    # Small queue to force drops under load.
    monkeypatch.setenv("TRACE_BROKER_QUEUE_MAX", "64")
    trace_id = "trace-flood-1"
    q = trace_broker.subscribe(trace_id)
    try:
        async def _run():
            n = 2000
            t0 = time.perf_counter()
            for i in range(n):
                decision_log.log_trace_event(
                    trace_id=trace_id,
                    event_type="flood",
                    source_type="agent",
                    source_id="Flood_Test",
                    target_type="system",
                    target_id=None,
                    payload={"i": i},
                )
            dt = time.perf_counter() - t0
            # This should not hang; generous upper bound to avoid flakiness.
            assert dt < 2.5

            # Let scheduled publish tasks run.
            await asyncio.sleep(0.05)
            assert q.qsize() <= 64

            # Drain queue and ensure we kept the newest tail.
            items = []
            while not q.empty():
                items.append(q.get_nowait())
            assert items
            tail = [it.get("payload", {}).get("i") for it in items if isinstance(it, dict)]
            assert max(tail) == n - 1
            assert min(tail) >= n - 64

        asyncio.run(_run())
    finally:
        trace_broker.unsubscribe(trace_id, q)
