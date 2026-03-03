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
import time
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
        self._local_expiry: dict[str, float] = {}
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
        exp = self._local_expiry.get(key)
        if exp is not None and exp < time.time():
            self._local.pop(key, None)
            self._local_expiry.pop(key, None)
            return None
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
            self._local_expiry[key] = time.time() + max(1, int(ex))
        except Exception:
            pass

    def set_safe(self, key: str, value: Any, *, source_id: str, trust_score: float, ex: Optional[int] = None) -> None:
        ts = int(time.time())
        wrapped = {
            "_meta": {
                "source_id": str(source_id or "unknown"),
                "trust_score": float(max(0.0, min(1.0, trust_score))),
                "created_at": ts,
                "quarantined": False,
                "poison_reason": None,
            },
            "value": value,
        }
        self.set(key, wrapped, ex=ex)

    def quarantine(self, key: str, reason: str = "suspected_poison") -> None:
        cur = self.get(key)
        if not isinstance(cur, dict):
            return
        meta = cur.get("_meta") if isinstance(cur.get("_meta"), dict) else {}
        meta["quarantined"] = True
        meta["poison_reason"] = str(reason or "suspected_poison")
        cur["_meta"] = meta
        self.set(key, cur, ex=self.default_ttl)

    def get_safe(self, key: str, *, min_trust: float = 0.3) -> Optional[Any]:
        cur = self.get(key)
        if not isinstance(cur, dict):
            return cur
        meta = cur.get("_meta") if isinstance(cur.get("_meta"), dict) else {}
        if bool(meta.get("quarantined")):
            return None
        trust = float(meta.get("trust_score") or 0.0)
        if trust < float(min_trust):
            return None
        return cur.get("value")
