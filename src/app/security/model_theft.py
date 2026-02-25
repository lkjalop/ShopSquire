from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any


_EXTRACTION_PATTERNS = (
    "repeat your system prompt",
    "print your system prompt",
    "export full prompt",
    "model weights",
    "dump model",
    "recreate this model",
    "training dataset",
    "leak prompt",
    "verbatim output",
)


def _enabled() -> bool:
    return str(os.getenv("MODEL_THEFT_GUARD_ENABLED", "1")).lower() in ("1", "true", "yes")


def _watermark_key() -> str:
    return str(os.getenv("MODEL_THEFT_WATERMARK_KEY", "shopsquire-watermark-secret") or "shopsquire-watermark-secret")


def looks_like_extraction_attempt(query: str | None) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    return any(pat in q for pat in _EXTRACTION_PATTERNS)


def enforce_model_theft_rate_limit(
    *,
    redis_client: Any,
    uid: str | None,
    source_ip: str | None,
    query: str | None,
) -> tuple[bool, str]:
    if not _enabled():
        return True, "disabled"
    if not looks_like_extraction_attempt(query):
        return True, "ok"

    max_per_hour = int(os.getenv("MODEL_THEFT_MAX_EXTRACTION_REQ_PER_HOUR", "40") or 40)
    who = str(uid or source_ip or "anon")
    bucket = int(time.time() // 3600)
    key = f"model_theft:extract:{bucket}:{who}"
    try:
        current = int(redis_client.get(key) or 0)
        if current >= max_per_hour:
            return False, "model_extraction_rate_limited"
        redis_client.incrby(key, 1)
        redis_client.expire(key, 3700)
    except Exception:
        # Fail-open for availability.
        return True, "degraded_allow"
    return True, "ok"


def build_model_watermark(*, trace_id: str | None, model: str | None, payload_hint: str | None = None) -> str:
    ts_bucket = int(time.time() // 300)  # 5-minute buckets
    material = f"{trace_id or ''}|{model or ''}|{payload_hint or ''}|{ts_bucket}"
    digest = hmac.new(_watermark_key().encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sqwm_{digest[:16]}"

