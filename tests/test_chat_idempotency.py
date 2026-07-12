"""Single-flight over the Idempotency-Key (review-7 P0): a duplicate request (the stream-timeout
→ /chat/query fallback carrying the same key) must NOT resolve the model twice — it returns the
first request's cached result. Fail-open when redis is flaky."""
import asyncio

from src.app.routers.chat import _idem_single_flight


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.locks = {}

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.locks:
            return False
        self.locks[k] = v
        return True

    def setex(self, k, ttl, v):
        self.store[k] = v

    def delete(self, k):
        self.locks.pop(k, None)


def test_duplicate_returns_cached_without_reproducing():
    r = _FakeRedis()
    calls = {"n": 0}

    async def producer():
        calls["n"] += 1
        return {"answer": calls["n"]}

    async def go():
        first = await _idem_single_flight(r, "chat:idem:k1", producer)
        second = await _idem_single_flight(r, "chat:idem:k1", producer)   # same key → cached
        return first, second

    first, second = asyncio.run(go())
    assert first == {"answer": 1}
    assert second == {"answer": 1}      # the cached result, not a fresh resolve
    assert calls["n"] == 1              # producer ran exactly ONCE


def test_distinct_keys_each_produce():
    r = _FakeRedis()
    calls = {"n": 0}

    async def producer():
        calls["n"] += 1
        return {"answer": calls["n"]}

    async def go():
        a = await _idem_single_flight(r, "chat:idem:a", producer)
        b = await _idem_single_flight(r, "chat:idem:b", producer)
        return a, b

    a, b = asyncio.run(go())
    assert a == {"answer": 1} and b == {"answer": 2} and calls["n"] == 2


def test_fail_open_when_redis_raises():
    class _BrokenRedis:
        def get(self, k): raise RuntimeError("down")
        def set(self, *a, **k): raise RuntimeError("down")
        def setex(self, *a, **k): raise RuntimeError("down")
        def delete(self, *a, **k): raise RuntimeError("down")

    calls = {"n": 0}

    async def producer():
        calls["n"] += 1
        return {"ok": True}

    out = asyncio.run(_idem_single_flight(_BrokenRedis(), "chat:idem:x", producer))
    assert out == {"ok": True} and calls["n"] == 1   # flaky redis never blocks the turn
