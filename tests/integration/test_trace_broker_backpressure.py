from src.app.services import trace_broker


def test_trace_broker_backpressure_drops_oldest(monkeypatch):
    import asyncio

    async def _run():
        monkeypatch.setenv("TRACE_BROKER_QUEUE_MAX", "3")
        trace_id = "trace-backpressure-1"
        q = trace_broker.subscribe(trace_id)
        try:
            # Publish more events than maxsize; broker should keep only the newest.
            for i in range(10):
                await trace_broker.publish(trace_id, {"i": i})

            assert q.qsize() == 3
            items = []
            while not q.empty():
                items.append(q.get_nowait())
            assert [it.get("i") for it in items] == [7, 8, 9]
        finally:
            trace_broker.unsubscribe(trace_id, q)

    asyncio.run(_run())
