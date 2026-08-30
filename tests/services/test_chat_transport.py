import asyncio

from src.app.services.chat_transport import idempotent_single_flight


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
