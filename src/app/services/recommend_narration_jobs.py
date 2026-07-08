"""Async narration job store — Tier 1b.

Lets `RECOMMEND_NARRATION_MODE=async` return the deterministic grounded answer INSTANTLY while the
(slow, 4.5s) LLM prose is computed in a background worker and fetched out-of-band via
`GET /api/v1/recommend/narration/{job_id}`. Result lands in Redis with a short TTL.

CORE / vertical-blind: no product-type assumptions. The narration fn is injected (no import cycle),
and it runs inside a copied context so the active StoreProfile propagates into the worker thread.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import uuid
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("shopsquire.narration_jobs")

_KEY = "narration_job:{job_id}"
_TTL_SECONDS = 300


def new_job_id() -> str:
    return uuid.uuid4().hex


def _key(job_id: str) -> str:
    return _KEY.format(job_id=str(job_id))


def put_narration(redis: Any, job_id: str, *, status: str, message: Optional[str], meta: Optional[Dict[str, Any]] = None) -> None:
    if redis is None:
        return
    record: Dict[str, Any] = {"status": status, "assistant_message": message}
    if meta:
        record.update(meta)
    with contextlib.suppress(Exception):
        redis.setex(_key(job_id), _TTL_SECONDS, json.dumps(record))


def get_narration(redis: Any, job_id: str) -> Optional[Dict[str, Any]]:
    """Return {status, assistant_message} or None if unknown/expired."""
    if redis is None:
        return None
    try:
        raw = redis.get(_key(job_id))
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("get_narration failed: %s", exc)
        return None


def run_narration_job(redis: Any, job_id: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Run the narration fn in this worker and persist its result. fn returns (message, _) or str,
    optionally with a third meta dict (e.g. guard-rejection violations) that rides in the job
    record so a no-prose outcome is DEBUGGABLE from the poll endpoint, never silent."""
    try:
        out = fn(*args, **kwargs)
        msg = out[0] if isinstance(out, tuple) else out
        meta = out[2] if isinstance(out, tuple) and len(out) > 2 and isinstance(out[2], dict) else None
        put_narration(redis, job_id, status="done", message=msg if isinstance(msg, str) else None, meta=meta)
    except Exception as exc:
        logger.debug("run_narration_job failed: %s", exc)
        put_narration(redis, job_id, status="error", message=None,
                      meta={"error": str(exc)[:200]})


def submit_narration(executor: Any, redis: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Enqueue a narration job; return its id. The worker inherits the current context (active
    StoreProfile) via copy_context().run. Marks the job 'pending' synchronously so an immediate poll
    sees a known state."""
    job_id = new_job_id()
    put_narration(redis, job_id, status="pending", message=None)
    ctx = contextvars.copy_context()
    executor.submit(ctx.run, run_narration_job, redis, job_id, fn, *args, **kwargs)
    return job_id
