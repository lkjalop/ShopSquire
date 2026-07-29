from __future__ import annotations

from src.app.services.scheduler_lease import SchedulerLease


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key, value, *, nx=False, px=None):
        del px
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, script, _keys, key, token, ttl_ms=None):
        if self.values.get(key) != token:
            return 0
        if ttl_ms is None:
            self.values.pop(key, None)
        return 1


def test_only_one_scheduler_owns_the_lease() -> None:
    redis = _FakeRedis()
    first = SchedulerLease(redis, key="scheduler", token="first", ttl_seconds=30)
    second = SchedulerLease(redis, key="scheduler", token="second", ttl_seconds=30)

    assert first.acquire() is True
    assert second.acquire() is False
    assert first.renew() is True


def test_stale_owner_cannot_renew_or_release_new_owner() -> None:
    redis = _FakeRedis()
    stale = SchedulerLease(redis, key="scheduler", token="stale", ttl_seconds=30)
    current = SchedulerLease(redis, key="scheduler", token="current", ttl_seconds=30)
    assert stale.acquire() is True
    redis.values["scheduler"] = "current"

    assert stale.renew() is False
    assert stale.release() is False
    assert redis.values["scheduler"] == "current"
    assert current.release() is True
