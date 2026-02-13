from __future__ import annotations

import time
from typing import Dict


def _cb_keys(name: str) -> Dict[str, str]:
    prefix = f"cb:{name}"
    return {
        "open_until": f"{prefix}:open_until",
        "window_start": f"{prefix}:window_start",
        "total": f"{prefix}:total",
        "errors": f"{prefix}:errors",
    }


def cb_is_open(redis, name: str, now_ts: int) -> bool:
    keys = _cb_keys(name)
    try:
        open_until = redis.get(keys["open_until"])
        return int(open_until or 0) > now_ts
    except Exception:
        return False


def cb_record(redis, name: str, success: bool, cfg: Dict) -> None:
    keys = _cb_keys(name)
    now_ts = int(time.time())
    window_seconds = int(cfg.get("window_seconds", 300))
    min_requests = int(cfg.get("min_requests", 10))
    error_rate_threshold = float(cfg.get("error_rate_threshold", 0.2))
    open_seconds = int(cfg.get("open_seconds", 120))
    try:
        window_start = int(redis.get(keys["window_start"]) or 0)
        if window_start == 0 or (now_ts - window_start) > window_seconds:
            redis.set(keys["window_start"], now_ts)
            redis.set(keys["total"], 0)
            redis.set(keys["errors"], 0)
        redis.incr(keys["total"], 1)
        if not success:
            redis.incr(keys["errors"], 1)
        total = int(redis.get(keys["total"]) or 0)
        errors = int(redis.get(keys["errors"]) or 0)
        if total >= min_requests and total > 0:
            rate = errors / max(total, 1)
            if rate >= error_rate_threshold:
                redis.set(keys["open_until"], now_ts + open_seconds)
    except Exception:
        pass
