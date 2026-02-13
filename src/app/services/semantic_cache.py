"""Redis-backed semantic cache with in-process fallback.

This provides a minimal interface used by `TierRouter` and other services:
- `get(key)` -> parsed value or None
- `set(key, value, ex=None)` -> store value (JSON-serializable)

If `REDIS_URL` is present in the environment and `redis` is installed, it will
use Redis; otherwise a process-local dict is used.
"""
from __future__ import annotations
import os
import json
from typing import Any, Optional

_has_redis = False
try:
    import redis
    _has_redis = True
except Exception:
    redis = None


class SemanticCache:
    def __init__(self, redis_url: Optional[str] = None, default_ttl: int = 3600):
        self.default_ttl = default_ttl
        self._local: dict[str, Any] = {}
        self._redis = None
        if redis_url and _has_redis:
            try:
                self._redis = redis.from_url(redis_url, decode_responses=True)
            except Exception:
                self._redis = None

    def get(self, key: str) -> Optional[Any]:
        if not key:
            return None
        # Try Redis first
        try:
            if self._redis:
                v = self._redis.get(key)
                if v is None:
                    return None
                try:
                    return json.loads(v)
                except Exception:
                    return v
        except Exception:
            pass

        # Fallback to local dict
        v = self._local.get(key)
        return v

    def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        if not key:
            return
        ex = ex or self.default_ttl
        try:
            if self._redis:
                payload = json.dumps(value, ensure_ascii=False)
                try:
                    # redis-py expects seconds
                    self._redis.set(name=key, value=payload, ex=int(ex))
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # Local store fallback
        try:
            self._local[key] = value
        except Exception:
            pass
