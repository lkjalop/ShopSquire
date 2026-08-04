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
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("shopsquire.narration_jobs")

_KEY = "narration_job:{job_id}"
_TTL_SECONDS = 300

# In-process fallback store (2026-07-09) — the async narration path used ONLY Redis, so when Redis
# is unreachable the app silently drops to DummyRedis: put_narration no-ops, get_narration returns
# None, and the poll endpoint returns 'pending' FOREVER — the buyer never sees model prose and there
# is no signal that the brain was muted (found via GPT-5.5's DummyRedis catch). The narration worker
# and the poll endpoint run in the SAME uvicorn process, so a module-level TTL dict makes async work
# WITHOUT Redis for the single-process demo, while Redis stays the multi-worker/production path.
# Writes go to BOTH; reads prefer Redis then fall back to memory. The record carries storage_backend
# so the state is fail-VISIBLE, never silently muted again.
_MEM_STORE: Dict[str, Tuple[float, str]] = {}
_MEM_LOCK = threading.Lock()


def _mem_put(job_id: str, record_json: str) -> None:
    now = time.time()
    with _MEM_LOCK:
        _MEM_STORE[str(job_id)] = (now + _TTL_SECONDS, record_json)
        if len(_MEM_STORE) > 512:  # bound growth: drop expired
            for k in [k for k, (exp, _) in _MEM_STORE.items() if exp < now]:
                _MEM_STORE.pop(k, None)


def _mem_get(job_id: str) -> Optional[str]:
    with _MEM_LOCK:
        item = _MEM_STORE.get(str(job_id))
        if not item:
            return None
        exp, rec = item
        if exp < time.time():
            _MEM_STORE.pop(str(job_id), None)
            return None
        return rec


def _redis_live(redis: Any) -> bool:
    """A real Redis client, not the DummyRedis no-op fallback (deps.DummyRedis)."""
    return redis is not None and type(redis).__name__ != "DummyRedis"


def new_job_id() -> str:
    return uuid.uuid4().hex


def _key(job_id: str) -> str:
    return _KEY.format(job_id=str(job_id))


_RESERVED_KEYS = ("status", "assistant_message")


def _redact_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """The job record is served VERBATIM to any client holding the job id, so meta must be
    category-level only (audit 2026-07-08): violation strings can embed the first 40 chars of a
    quarantined URL and error strings can embed internal hosts/paths. Reserved keys are dropped
    so a producer's meta can never shadow the record's own lifecycle fields."""
    out: Dict[str, Any] = {}
    for k, v in meta.items():
        if k in _RESERVED_KEYS:
            continue
        if k == "violations" and isinstance(v, list):
            # keep the class before the ':' ("ungrounded_url:https://evil..." -> "ungrounded_url")
            out[k] = sorted({str(x).split(":", 1)[0] for x in v})[:6]
        elif k == "error":
            out[k] = "narration_job_failed"
        else:
            out[k] = v
    return out


def put_narration(redis: Any, job_id: str, *, status: str, message: Optional[str], meta: Optional[Dict[str, Any]] = None) -> None:
    record: Dict[str, Any] = {"status": status, "assistant_message": message}
    if meta:
        record.update(_redact_meta(meta))
    live = _redis_live(redis)
    record["storage_backend"] = "redis" if live else "memory"  # fail-visible
    record_json = json.dumps(record)
    # Always write to the in-process store (works single-process WITHOUT Redis); ALSO write to Redis
    # when it's real, so a multi-worker deployment can read across processes.
    _mem_put(job_id, record_json)
    if live:
        with contextlib.suppress(Exception):
            redis.setex(_key(job_id), _TTL_SECONDS, record_json)


def get_narration(redis: Any, job_id: str) -> Optional[Dict[str, Any]]:
    """Return {status, assistant_message, storage_backend} or None if unknown/expired. Prefers
    Redis (cross-process), falls back to the in-process store so single-process async works
    without Redis (2026-07-09)."""
    if _redis_live(redis):
        try:
            raw = redis.get(_key(job_id))
            if raw is not None:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8")
                out = json.loads(raw)
                if isinstance(out, dict):
                    return out
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("get_narration redis read failed: %s", exc)
    raw = _mem_get(job_id)
    if raw is None:
        return None
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except Exception:
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
