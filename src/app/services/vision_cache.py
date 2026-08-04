"""Image-hash cache for expensive vision-LLM results.

The vision model (qwen2.5vl / llava via Ollama) is the dominant latency in the
image path — measured at 52–86s end-to-end (2026-06-15), because it runs once for
product identity (`product_identity_agent.identify_product_from_image`) AND once
for CV labels/text (`cv_provider.get_labels_and_text`), with no caching. Repeating
the SAME image (every live demo, every retry, every multi-agent fan-out on one
upload) re-pays the full cost.

This is a tiny, fail-open cache keyed by sha256(image_bytes) + namespace, with a
TTL and an LRU bound. On a cache hit the vision call is skipped entirely, which
takes a repeated demo image from ~86s to <1s. It is deliberately process-local
and dependency-free; correctness never depends on it (a miss just recomputes).

Pre-warm the demo image set with scripts/prewarm_demo_cache.py so even the FIRST
on-stage upload is instant.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any, Optional

_CACHE: "dict[str, tuple[float, Any]]" = {}
_LOCK = threading.Lock()
_TTL_SECONDS = int(os.getenv("VISION_CACHE_TTL", "3600") or 3600)
_MAX_ENTRIES = int(os.getenv("VISION_CACHE_MAX", "512") or 512)


def _enabled() -> bool:
    return str(os.getenv("VISION_CACHE_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")


def image_key(image_bytes: bytes | None, namespace: str) -> str:
    """Stable cache key for an image under a result namespace (e.g. 'identity',
    'labels:visual_search'). Different prompts/modes must use different namespaces."""
    digest = hashlib.sha256(bytes(image_bytes or b"")).hexdigest()
    return f"{namespace}:{digest}"


def get(key: str) -> Optional[Any]:
    if not _enabled():
        return None
    now = time.time()
    with _LOCK:
        entry = _CACHE.get(key)
        if not entry:
            _record("miss")
            return None
        ts, value = entry
        if now - ts > _TTL_SECONDS:
            _CACHE.pop(key, None)
            _record("miss")
            return None
        _record("hit")
        return value


def put(key: str, value: Any) -> None:
    if not _enabled() or value is None:
        return
    with _LOCK:
        if len(_CACHE) >= _MAX_ENTRIES:
            # drop the oldest ~10% to bound memory
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: max(1, _MAX_ENTRIES // 10)]:
                _CACHE.pop(k, None)
        _CACHE[key] = (time.time(), value)


def clear() -> None:
    with _LOCK:
        _CACHE.clear()


def _record(outcome: str) -> None:
    try:
        from src.app.observability.metrics import record_vision_cache
        record_vision_cache(outcome)
    except Exception:
        pass
