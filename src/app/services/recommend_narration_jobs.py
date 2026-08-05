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
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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
_DEDICATED_EXECUTOR: ThreadPoolExecutor | None = None
_DEDICATED_SLOTS: threading.BoundedSemaphore | None = None
_DEDICATED_LOCK = threading.Lock()


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


_NARRATION_FINGERPRINT_FIELDS = (
    "tenant_id", "subject_id", "session_epoch", "decision_id", "sku", "quantity",
    "currency", "destination_token", "required_by", "fulfillment_route",
    "supplier_promise_version", "evidence_digest", "model_version", "prompt_version",
    "policy_version",
)


def narration_decision_fingerprint(material: Dict[str, Any]) -> str:
    """Hash a closed, commercially complete narration identity; never hash generated prose."""
    normalized = {key: material.get(key) for key in _NARRATION_FINGERPRINT_FIELDS}
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def observe_narration_fingerprint(
    redis: Any, *, tenant_id: str, subject_id: str, session_epoch: str,
    fingerprint: str, ttl_seconds: int = 300,
) -> Dict[str, Any]:
    """Measure duplicate work without reusing prose or changing the job lifecycle."""
    scope = hashlib.sha256(
        f"{tenant_id}|{subject_id}|{session_epoch}".encode("utf-8")
    ).hexdigest()[:24]
    key = f"narration_fingerprint:v1:{scope}:{str(fingerprint)}"
    first_seen = True
    if redis is not None:
        try:
            result = redis.set(key, "1", nx=True, ex=max(30, min(int(ttl_seconds), 3600)))
            first_seen = bool(result)
        except Exception:
            first_seen = True
    outcome = "first_seen" if first_seen else "duplicate_candidate"
    try:
        from src.app.observability.metrics import record_narration_fingerprint

        record_narration_fingerprint(outcome)
    except Exception:
        pass
    return {"outcome": outcome, "fingerprint": str(fingerprint), "prose_reused": False,
            "measurement_only": True, "scope_hash": scope}


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


def run_narration_job(redis: Any, job_id: str, fn: Callable[..., Any], *args: Any,
                      _job_meta: Optional[Dict[str, Any]] = None, **kwargs: Any) -> None:
    """Run the narration fn in this worker and persist its result. fn returns (message, _) or str,
    optionally with a third meta dict (e.g. guard-rejection violations) that rides in the job
    record so a no-prose outcome is DEBUGGABLE from the poll endpoint, never silent."""
    try:
        out = fn(*args, **kwargs)
        msg = out[0] if isinstance(out, tuple) else out
        meta = out[2] if isinstance(out, tuple) and len(out) > 2 and isinstance(out[2], dict) else None
        put_narration(redis, job_id, status="done", message=msg if isinstance(msg, str) else None,
                      meta={**(_job_meta or {}), **(meta or {})})
    except Exception as exc:
        logger.debug("run_narration_job failed: %s", exc)
        put_narration(redis, job_id, status="error", message=None,
                      meta={**(_job_meta or {}), "error": str(exc)[:200]})


def narration_runtime_contract() -> Dict[str, Any]:
    workers = max(1, min(int(os.getenv("NARRATION_EXECUTOR_WORKERS", "2") or 2), 32))
    queue = max(workers, min(int(os.getenv("NARRATION_EXECUTOR_QUEUE", "8") or 8), 512))
    endpoint = str(os.getenv("OLLAMA_NARRATION_URL", "") or "").strip()
    router_endpoint = str(os.getenv("OLLAMA_URL", "") or "").strip()
    return {
        "dedicated_executor": str(os.getenv("NARRATION_DEDICATED_EXECUTOR", "1")).lower()
        in {"1", "true", "yes", "on"},
        "workers": workers,
        "queue_capacity": queue,
        "model": str(os.getenv("OLLAMA_NARRATION_MODEL", os.getenv("OLLAMA_SUMMARY_MODEL", "")) or ""),
        "endpoint_configured": bool(endpoint),
        "endpoint_isolated_from_router": bool(endpoint and endpoint != router_endpoint),
        "resource_authority": "bounded_background_only",
    }


def _dedicated_resources() -> tuple[ThreadPoolExecutor, threading.BoundedSemaphore]:
    global _DEDICATED_EXECUTOR, _DEDICATED_SLOTS
    with _DEDICATED_LOCK:
        if _DEDICATED_EXECUTOR is None or _DEDICATED_SLOTS is None:
            contract = narration_runtime_contract()
            _DEDICATED_EXECUTOR = ThreadPoolExecutor(
                max_workers=int(contract["workers"]), thread_name_prefix="narration",
            )
            _DEDICATED_SLOTS = threading.BoundedSemaphore(int(contract["queue_capacity"]))
    return _DEDICATED_EXECUTOR, _DEDICATED_SLOTS


def shutdown_narration_resources(*, wait: bool = False) -> None:
    """Release the process-local narration pool during app or test shutdown.

    The pool is lazy and may be recreated by a later app instance.  Clearing the
    module references under the same lock prevents a concurrent submitter from
    receiving an executor that has already begun shutting down.
    """
    global _DEDICATED_EXECUTOR, _DEDICATED_SLOTS
    with _DEDICATED_LOCK:
        executor = _DEDICATED_EXECUTOR
        _DEDICATED_EXECUTOR = None
        _DEDICATED_SLOTS = None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=True)


def submit_narration(executor: Any, redis: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Enqueue a narration job; return its id. The worker inherits the current context (active
    StoreProfile) via copy_context().run. Marks the job 'pending' synchronously so an immediate poll
    sees a known state."""
    job_id = new_job_id()
    contract = narration_runtime_contract()
    use_dedicated = bool(contract["dedicated_executor"] or executor is None)
    meta = {"resource_pool": "dedicated_narration" if use_dedicated else "caller_executor",
            "model": contract["model"], "endpoint_isolated": contract["endpoint_isolated_from_router"]}
    put_narration(redis, job_id, status="pending", message=None, meta=meta)
    ctx = contextvars.copy_context()
    submitted_at = time.monotonic()

    def _record_queue_wait() -> None:
        try:
            from src.app.observability.metrics import record_narration_queue_wait

            record_narration_queue_wait(time.monotonic() - submitted_at)
        except Exception:
            pass

    if use_dedicated:
        dedicated, slots = _dedicated_resources()
        if not slots.acquire(blocking=False):
            put_narration(redis, job_id, status="degraded", message=None,
                          meta={**meta, "reason": "narration_queue_saturated"})
            return job_id

        def _bounded_run() -> None:
            try:
                _record_queue_wait()
                ctx.run(run_narration_job, redis, job_id, fn, *args, _job_meta=meta, **kwargs)
            finally:
                slots.release()

        dedicated.submit(_bounded_run)
    else:
        def _caller_run() -> None:
            _record_queue_wait()
            ctx.run(run_narration_job, redis, job_id, fn, *args, _job_meta=meta, **kwargs)

        executor.submit(_caller_run)
    return job_id
