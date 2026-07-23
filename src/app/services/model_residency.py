"""Bounded model-residency transitions for constrained local demo hardware."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict

logger = logging.getLogger("shopsquire.model_residency")

_LOCK = threading.Lock()
_TIMER: threading.Timer | None = None
_STATUS: Dict[str, Any] = {"status": "idle"}


def router_restore_status() -> Dict[str, Any]:
    with _LOCK:
        return dict(_STATUS)


def _restore_router() -> None:
    started = time.monotonic()
    model = os.getenv("ROUTER_MODEL", "qwen3:14b")
    try:
        import httpx

        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        response = httpx.post(
            f"{url}/api/generate",
            json={
                "model": model,
                "prompt": "ok",
                "stream": False,
                "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                "options": {"num_predict": 1, "temperature": 0},
            },
            timeout=max(5.0, min(float(os.getenv("CV_ROUTER_RESTORE_TIMEOUT_SEC", "90") or 90), 180.0)),
        )
        response.raise_for_status()
        status = "ready"
        error = None
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {str(exc)[:180]}"
        logger.warning("post-image router restore failed: %s", error)
    with _LOCK:
        _STATUS.clear()
        _STATUS.update({
            "status": status,
            "model": model,
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
        })
        if error:
            _STATUS["error"] = error


def schedule_router_restore() -> bool:
    """Debounce concurrent image completions into one background router restore."""
    enabled = str(os.getenv("CV_RESTORE_TEXT_ROUTER_AFTER_IMAGE", "1") or "1").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False
    delay = max(0.1, min(float(os.getenv("CV_ROUTER_RESTORE_DELAY_SEC", "0.5") or 0.5), 10.0))
    global _TIMER
    with _LOCK:
        if _TIMER is not None and _TIMER.is_alive():
            _TIMER.cancel()
        _STATUS.clear()
        _STATUS.update({"status": "scheduled", "delay_seconds": delay})
        _TIMER = threading.Timer(delay, _restore_router)
        _TIMER.name = "post-image-router-restore"
        _TIMER.daemon = True
        _TIMER.start()
    return True
