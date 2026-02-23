from __future__ import annotations

import time
import threading
from typing import Dict, Tuple
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# Simple in-memory sliding window rate limiter. In production replace driver with Redis.

_LOCK = threading.Lock()
_STATE: Dict[str, Tuple[float, int]] = {}

DEFAULT_PER_MIN_KEY = int(__import__("os").getenv("RATE_LIMIT_PER_MINUTE_KEY", "120"))
DEFAULT_PER_MIN_IP = int(__import__("os").getenv("RATE_LIMIT_PER_MINUTE_IP", "60"))

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_min_key: int = DEFAULT_PER_MIN_KEY, per_min_ip: int = DEFAULT_PER_MIN_IP):
        super().__init__(app)
        self.per_min_key = int(per_min_key)
        self.per_min_ip = int(per_min_ip)

    async def dispatch(self, request: Request, call_next):
        try:
            # Non-positive values mean rate limiting is disabled for that scope.
            enforce_key = self.per_min_key > 0
            enforce_ip = self.per_min_ip > 0
            if not enforce_key and not enforce_ip:
                return await call_next(request)

            now = time.time()
            # determine bucket keys
            hdr_key = request.headers.get("x-api-key") or request.cookies.get("shopsquire_api_key") or "anon"
            ip = request.client.host if request.client else "unknown"
            key_bucket = f"k:{hdr_key}"
            ip_bucket = f"i:{ip}"
            over = False
            reason = None
            with _LOCK:
                # key bucket
                ts, cnt = _STATE.get(key_bucket, (now, 0))
                if now - ts >= 60:
                    ts, cnt = now, 0
                cnt += 1
                _STATE[key_bucket] = (ts, cnt)
                if enforce_key and cnt > self.per_min_key:
                    over = True
                    reason = f"key_rate_limit_exceeded ({self.per_min_key}/min)"
                # ip bucket
                ts2, cnt2 = _STATE.get(ip_bucket, (now, 0))
                if now - ts2 >= 60:
                    ts2, cnt2 = now, 0
                cnt2 += 1
                _STATE[ip_bucket] = (ts2, cnt2)
                if enforce_ip and cnt2 > self.per_min_ip:
                    over = True
                    reason = f"ip_rate_limit_exceeded ({self.per_min_ip}/min)"
            if over:
                raise HTTPException(status_code=429, detail=reason)
        except HTTPException:
            raise
        except Exception:
            pass
        return await call_next(request)
