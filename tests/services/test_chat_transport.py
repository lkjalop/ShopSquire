import asyncio

from src.app.services.chat_transport import (
    idempotent_single_flight,
    retained_operation_progress,
    retained_operation_task,
)


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def setex(self, key, ttl, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def test_sse_and_query_share_the_same_completed_envelope():
    redis = FakeRedis()
    calls = 0

    async def producer():
        nonlocal calls
        calls += 1
        return {"status": "completed", "case_revision": 7, "turn_read_model": {"case_revision": 7}}

    first = asyncio.run(idempotent_single_flight(redis, "chat:idem:turn-7", producer))
    second = asyncio.run(idempotent_single_flight(redis, "chat:idem:turn-7", producer))
    assert first == second
    assert calls == 1


def test_in_progress_response_carries_retrievable_operation_identity():
    redis = FakeRedis()
    redis.set("chat:idem:turn-8:lock", "other", nx=True, ex=90)

    async def producer():
        raise AssertionError("second producer must not run")

    result = asyncio.run(idempotent_single_flight(
        redis,
        "chat:idem:turn-8",
        producer,
        wait_timeout_seconds=0,
        in_progress_factory=lambda operation: {
            "status": "in_progress", "operation_id": f"chat:{operation}",
        },
    ))
    assert result == {"status": "in_progress", "operation_id": "chat:turn-8"}


def test_timed_out_wait_does_not_cancel_or_duplicate_retained_operation():
    async def scenario():
        calls = 0
        release = asyncio.Event()

        async def producer():
            nonlocal calls
            calls += 1
            await release.wait()
            return {"status": "completed", "operation_id": "chat:turn-9"}

        first, created = retained_operation_task("chat:idem:turn-9", producer)
        assert created is True
        try:
            await asyncio.wait_for(asyncio.shield(first), timeout=0.001)
        except asyncio.TimeoutError:
            pass
        second, created_again = retained_operation_task("chat:idem:turn-9", producer)
        assert second is first
        assert created_again is False
        assert not second.cancelled()
        progress = retained_operation_progress("chat:idem:turn-9")
        assert progress["status"] == "running"
        assert progress["elapsed_ms"] is not None
        assert progress["stage"]
        release.set()
        assert await second == {"status": "completed", "operation_id": "chat:turn-9"}
        assert calls == 1

    asyncio.run(scenario())


def test_single_flight_caches_terminal_failure_for_later_pollers():
    redis = FakeRedis()
    calls = 0

    async def producer():
        nonlocal calls
        calls += 1
        raise RuntimeError("sensitive upstream detail")

    def failed(operation_key, exc):
        return {
            "status": "failed",
            "operation_id": f"chat:{operation_key}",
            "failure_code": "chat_operation_failed",
            "products": [],
        }

    first = asyncio.run(idempotent_single_flight(
        redis, "chat:idem:broken-turn", producer, error_factory=failed,
    ))
    second = asyncio.run(idempotent_single_flight(
        redis, "chat:idem:broken-turn", producer, error_factory=failed,
    ))

    assert first == second
    assert first["status"] == "failed"
    assert "sensitive" not in str(first)
    assert calls == 1
