import asyncio


def test_log_trace_event_db_down_still_publishes(monkeypatch):
    from src.app.services import decision_log
    from src.app.services import trace_broker

    class _BoomSession:
        def __enter__(self):
            raise RuntimeError("db_down")

        def __exit__(self, exc_type, exc, tb):
            return False

    # Simulate DB being down: opening a session fails.
    monkeypatch.setattr(decision_log, "db_session", lambda: _BoomSession())

    trace_id = "trace-db-down-1"
    monkeypatch.setenv("TRACE_BROKER_QUEUE_MAX", "5")
    q = trace_broker.subscribe(trace_id)
    try:
        async def _run():
            decision_log.log_trace_event(
                trace_id=trace_id,
                event_type="db_down_test",
                source_type="agent",
                source_id="Chaos_Test",
                target_type="system",
                target_id=None,
                payload={"hello": "world"},
            )
            # Wait briefly for background publication.
            ev = await asyncio.wait_for(q.get(), timeout=2.0)
            assert ev.get("event_type") == "db_down_test"
            assert (ev.get("payload") or {}).get("hello") == "world"

        asyncio.run(_run())
    finally:
        trace_broker.unsubscribe(trace_id, q)

