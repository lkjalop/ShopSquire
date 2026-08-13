from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Dict, Tuple, Optional, List

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.app.deps import get_redis

try:
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - Redis is optional in minimal local installs.
    RedisError = OSError  # type: ignore[misc,assignment]

_REDIS_OPERATION_ERRORS = (RedisError, AttributeError, TypeError, ValueError, RuntimeError)

# Fallback local stores when Redis is unavailable (dev/test).
_LOCK = threading.Lock()
_STATE: Dict[str, Tuple[float, int]] = {}
_CONCURRENCY_STATE: Dict[str, int] = {}
_SLIDING_STATE: Dict[str, List[float]] = {}

DEFAULT_PER_MIN_KEY = int(os.getenv("RATE_LIMIT_PER_MINUTE_KEY", "120"))
DEFAULT_PER_MIN_IP = int(os.getenv("RATE_LIMIT_PER_MINUTE_IP", "60"))


def _hash_token(value: str) -> str:
    raw = str(value or "").encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:24]


def _redis_client():
    try:
        r = get_redis()
        if r.__class__.__name__ == "DummyRedis":
            return None
        return r
    except Exception:
        return None


def consume_fixed_window_limit(
    *,
    key: str,
    limit: int,
    window_sec: int,
    fallback_store: Optional[Dict[str, Tuple[float, int]]] = None,
    now_ts: Optional[float] = None,
) -> bool:
    """Consume one token from a fixed-window limiter.

    Returns True when request is allowed, False when over limit.
    """
    if int(limit or 0) <= 0:
        return True
    win = max(1, int(window_sec or 60))
    redis_key = f"ratelimit:fw:{key}"

    r = _redis_client()
    if r is not None:
        try:
            cnt = int(r.incrby(redis_key, 1) or 0)
            if cnt == 1:
                r.expire(redis_key, win)
            return cnt <= int(limit)
        except _REDIS_OPERATION_ERRORS:
            # Fall through to in-memory fallback.
            pass

    store = fallback_store if isinstance(fallback_store, dict) else _STATE
    now = float(now_ts if now_ts is not None else time.time())
    with _LOCK:
        ts, cnt = store.get(key, (now, 0))
        if now - float(ts) >= float(win):
            ts, cnt = now, 0
        cnt = int(cnt) + 1
        store[key] = (ts, cnt)
        return cnt <= int(limit)


def consume_sliding_window_limit(
    *,
    key: str,
    limit: int,
    window_sec: int,
    fallback_store: Optional[Dict[str, List[float]]] = None,
    now_ts: Optional[float] = None,
) -> bool:
    """Consume one token from a sliding-window limiter.

    Returns True when request is allowed, False when over limit.
    """
    if int(limit or 0) <= 0:
        return True
    win = max(1, int(window_sec or 60))
    now = float(now_ts if now_ts is not None else time.time())
    start_ts = now - float(win)

    redis_key = f"ratelimit:sw:{key}"
    r = _redis_client()
    if r is not None:
        try:
            # Prefer Redis sorted-set implementation when available.
            if hasattr(r, "zadd") and hasattr(r, "zcard"):
                member = f"{now}:{time.time_ns()}"
                r.zremrangebyscore(redis_key, "-inf", start_ts)
                count = int(r.zcard(redis_key) or 0)
                if count >= int(limit):
                    return False
                r.zadd(redis_key, {member: now})
                r.expire(redis_key, win)
                return True
        except _REDIS_OPERATION_ERRORS:
            pass

    store = fallback_store if isinstance(fallback_store, dict) else _SLIDING_STATE
    with _LOCK:
        arr = list(store.get(key, []))
        arr = [float(ts) for ts in arr if float(ts) > start_ts]
        if len(arr) >= int(limit):
            store[key] = arr
            return False
        arr.append(now)
        store[key] = arr
        return True


def acquire_concurrency_slot(
    *,
    key: str,
    limit: int,
    ttl_sec: int = 60,
    fallback_store: Optional[Dict[str, int]] = None,
) -> bool:
    """Acquire a distributed concurrency slot.

    Returns True if slot acquired, False when capacity is exhausted.
    """
    if int(limit or 0) <= 0:
        return True
    ttl = max(1, int(ttl_sec or 60))
    redis_key = f"ratelimit:conc:{key}"

    r = _redis_client()
    if r is not None:
        try:
            cnt = int(r.incrby(redis_key, 1) or 0)
            if cnt == 1:
                r.expire(redis_key, ttl)
            if cnt > int(limit):
                try:
                    r.incrby(redis_key, -1)
                except Exception:
                    pass
                return False
            return True
        except _REDIS_OPERATION_ERRORS:
            pass

    store = fallback_store if isinstance(fallback_store, dict) else _CONCURRENCY_STATE
    with _LOCK:
        cur = int(store.get(key, 0))
        if cur >= int(limit):
            return False
        store[key] = cur + 1
        return True


def release_concurrency_slot(*, key: str, fallback_store: Optional[Dict[str, int]] = None) -> None:
    redis_key = f"ratelimit:conc:{key}"
    r = _redis_client()
    if r is not None:
        try:
            rem = int(r.incrby(redis_key, -1) or 0)
            if rem <= 0:
                r.delete(redis_key)
            return
        except _REDIS_OPERATION_ERRORS:
            pass

    store = fallback_store if isinstance(fallback_store, dict) else _CONCURRENCY_STATE
    with _LOCK:
        cur = int(store.get(key, 0))
        nxt = cur - 1
        if nxt <= 0:
            store.pop(key, None)
        else:
            store[key] = nxt


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_min_key: int = DEFAULT_PER_MIN_KEY, per_min_ip: int = DEFAULT_PER_MIN_IP):
        super().__init__(app)
        self.per_min_key = int(per_min_key)
        self.per_min_ip = int(per_min_ip)

    async def dispatch(self, request: Request, call_next):
        try:
            # Browser CORS preflight is metadata negotiation, not an application
            # operation. Counting it can strand an otherwise permitted request
            # behind a 429 response that lacks the CORS headers the browser needs
            # to expose the real outcome.
            if request.method.upper() == "OPTIONS":
                return await call_next(request)
            enforce_key = self.per_min_key > 0
            enforce_ip = self.per_min_ip > 0
            if not enforce_key and not enforce_ip:
                return await call_next(request)

            hdr_raw = request.headers.get("x-api-key") or request.cookies.get("shopsquire_api_key") or "anon"
            hdr_key = _hash_token(hdr_raw)
            from src.app.security.client_ip import client_ip

            ip = client_ip(request)
            key_bucket = f"key:{hdr_key}"
            ip_bucket = f"ip:{ip}"

            if enforce_key and not consume_fixed_window_limit(key=key_bucket, limit=self.per_min_key, window_sec=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"key_rate_limit_exceeded ({self.per_min_key}/min)"},
                )
            if enforce_ip and not consume_fixed_window_limit(key=ip_bucket, limit=self.per_min_ip, window_sec=60):
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"ip_rate_limit_exceeded ({self.per_min_ip}/min)"},
                )
        except _REDIS_OPERATION_ERRORS:
            # Fail-open by design for middleware stability; detailed limits are
            # still enforced by route-level backpressure middleware.
            pass
        return await call_next(request)
