from __future__ import annotations

import time
from typing import Any, Dict

from src.app.deps import get_redis
from src.app.models.db import db_session


_CACHE: Dict[str, Any] = {"ts": 0, "payload": None}
_CACHE_TTL_SECONDS = 30


def _check_db() -> Dict[str, Any]:
    start = time.time()
    try:
        with db_session() as db:
            db.execute("SELECT 1")
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency_ms, "last_ok": int(time.time())}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc), "last_ok": None, "latency_ms": None}


def _check_redis() -> Dict[str, Any]:
    start = time.time()
    try:
        redis_client = get_redis()
        if hasattr(redis_client, "ping"):
            redis_client.ping()
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency_ms, "last_ok": int(time.time())}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc), "last_ok": None, "latency_ms": None}


def dependency_health_snapshot(force: bool = False) -> Dict[str, Any]:
    now = int(time.time())
    if not force and _CACHE.get("payload") and (now - int(_CACHE.get("ts", 0))) < _CACHE_TTL_SECONDS:
        return _CACHE["payload"]

    db_status = _check_db()
    redis_status = _check_redis()
    payload = {
        "timestamp": now,
        "dependencies": {
            "db": db_status,
            "redis": redis_status,
        },
    }
    _CACHE["ts"] = now
    _CACHE["payload"] = payload
    return payload
