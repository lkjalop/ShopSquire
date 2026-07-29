from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

_RENEW_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("pexpire", KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""


@dataclass
class SchedulerLease:
    """Token-bound Redis lease preventing duplicate scheduler execution."""

    redis: Any
    key: str = "shopsquire:scheduler:beat"
    ttl_seconds: int = 45
    token: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def ttl_ms(self) -> int:
        return max(5, int(self.ttl_seconds)) * 1000

    def acquire(self) -> bool:
        return bool(self.redis.set(self.key, self.token, nx=True, px=self.ttl_ms))

    def renew(self) -> bool:
        return bool(
            self.redis.eval(
                _RENEW_SCRIPT,
                1,
                self.key,
                self.token,
                self.ttl_ms,
            )
        )

    def release(self) -> bool:
        return bool(
            self.redis.eval(
                _RELEASE_SCRIPT,
                1,
                self.key,
                self.token,
            )
        )


def scheduler_lease_from_env() -> SchedulerLease:
    import redis

    redis_url = (
        os.getenv("SCHEDULER_REDIS_URL")
        or os.getenv("REDIS_URL")
        or os.getenv("CELERY_BROKER_URL")
    )
    if not redis_url:
        raise RuntimeError("scheduler_lease_redis_url_missing")
    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    ttl = int(os.getenv("SCHEDULER_LEASE_TTL_SEC", "45") or 45)
    key = os.getenv("SCHEDULER_LEASE_KEY", "shopsquire:scheduler:beat")
    return SchedulerLease(client, key=key, ttl_seconds=ttl)
