"""Transport reliability primitives independent from recommendation orchestration."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from typing import Dict
import hashlib
import os
from threading import RLock

_CHAT_REPLAY_LOCAL: Dict[str, float] = {}
_CHAT_REPLAY_LOCK = RLock()
logger = logging.getLogger(__name__)


def chat_replay_digest(*,tenant_id,uid,session_id,source_ip,query,nonce,shape,memory_mode,case_id):
    """Duplicate requests are scoped to one tenant, buyer, mode and case."""
    material=dict(tenant_id=tenant_id,uid=uid,session_id=session_id or '',source_ip=source_ip or '',
        query=str(query or '').strip().lower()[:500],nonce=nonce or '',shape=shape if not nonce else {},
        memory_mode=memory_mode,case_id=case_id or '')
    return hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _chat_in_progress(
    *, idempotency_key: str = "", execution_progress: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    operation_key = str(idempotency_key or "")[:128] or None
    return {
        "status": "in_progress",
        "schema_version": "completed-turn-envelope.v1",
        "retryable": True,
        "retry_after_ms": 2000,
        "idempotency_key": operation_key,
        "operation_id": f"chat:{operation_key}" if operation_key else None,
        "recommendation_status": "pending",
        "research_status": "pending",
        "catalog_authority": "blocked_pending_completion",
        "catalog_scope": None,
        "catalog_scope_status": "pending",
        "commerce_authority": "none",
        "products": [],
        "action_executed": False,
        "execution_progress": dict(execution_progress or {}),
        "retrieval": {
            "method": "POST",
            "path": "/api/v1/chat/query",
            "idempotency_key": operation_key,
        },
        "assistant_message": (
            "I’m still working on that request. Retrying with the same "
            "request key will return the completed result without running it twice."
        ),
    }


def _chat_operation_failed(
    *, idempotency_key: str = "", exc: Exception | None = None,
) -> Dict[str, Any]:
    """Fail closed when a retained operation dies after its initial ACK."""
    operation_key = str(idempotency_key or "")[:128] or None
    operation_id = f"chat:{operation_key}" if operation_key else None
    failure_code = (
        "chat_operation_deadline_exceeded"
        if isinstance(exc, asyncio.TimeoutError) else "chat_operation_failed"
    )
    terminal = {
        "operation_id": operation_id,
        "case_id": None,
        "case_revision": None,
        "recommendation_status": "failed",
        "research_status": "failed",
        "catalog_authority": "blocked",
        "catalog_scope": None,
        "catalog_scope_status": "unavailable",
        "commerce_authority": "none",
        "product_shelves": [],
        "failure_code": failure_code,
    }
    return {
        "status": "failed",
        "schema_version": "completed-turn-envelope.v1",
        "assistant_message": (
            "This request could not complete within its governed execution path. "
            "No recommendation or commercial action was authorized."
        ),
        **terminal,
        "products": [],
        "action_executed": False,
        "execution_evidence": {
            "component": "chat_operation",
            "status": "failed",
            "failure_code": failure_code,
            "fallback_used": False,
            "operation_id": operation_id,
        },
        "terminal_outcome": terminal,
    }


def _chat_idempotency_cache_key(
    *, tenant_id: str, uid: str, session_id: str, idempotency_key: str,
) -> str:
    """Scope a caller-controlled operation key without placing identity in Redis keys."""
    scope = hashlib.sha256(
        f"{tenant_id}|{uid}|{session_id}".encode("utf-8")
    ).hexdigest()[:24]
    operation = str(idempotency_key or "").strip()[:128]
    return f"chat:idem:{scope}:{operation}"


def _chat_request_timeout_seconds() -> float:
    try:
        configured = float(os.getenv("CHAT_REQUEST_TIMEOUT_SEC", "30") or 30)
    except (TypeError, ValueError):
        configured = 30.0
    return max(0.1, min(configured, 120.0))


def _automatic_research_timeout_seconds() -> float:
    """Return the deadline for the complete governed research pipeline.

    Discovery, identity resolution, official-origin fetch and typed extraction
    each have smaller internal limits. The former hard-coded 20 second wrapper
    was shorter than their valid serial critical path and cancelled successful
    work after the official page had already been fetched.
    """

    try:
        configured = float(os.getenv("AUTOMATIC_RESEARCH_TIMEOUT_SEC", "45") or 45)
    except (TypeError, ValueError):
        configured = 45.0
    return max(10.0, min(configured, 120.0))


def _chat_replay_mark_once(redis, *, replay_key: str, ttl_seconds: int) -> bool:
    ttl = max(1, int(ttl_seconds or 1))
    redis_key = f"chat:replay:{replay_key}"
    try:
        # NX+EX ensures only the first request in the replay window is accepted.
        ok = redis.set(redis_key, "1", ex=ttl, nx=True)
        return bool(ok)
    except Exception:
        now = time.time()
        with _CHAT_REPLAY_LOCK:
            exp = float(_CHAT_REPLAY_LOCAL.get(replay_key) or 0.0)
            if exp > now:
                return False
            _CHAT_REPLAY_LOCAL[replay_key] = now + ttl
            stale = [k for k, v in _CHAT_REPLAY_LOCAL.items() if float(v or 0.0) <= now]
            for k in stale[:128]:
                _CHAT_REPLAY_LOCAL.pop(k, None)
        return True


async def _idem_single_flight(
    redis,
    key: str,
    producer,
    *,
    wait_timeout_seconds: float = 2.0,
):
    from src.app.services.chat_transport import idempotent_single_flight

    return await idempotent_single_flight(
        redis, key, producer, wait_timeout_seconds=wait_timeout_seconds,
        in_progress_factory=lambda idem_key: _chat_in_progress(idempotency_key=idem_key),
        error_factory=lambda idem_key, exc: _chat_operation_failed(
            idempotency_key=idem_key, exc=exc,
        ),
        logger=logger,
    )



# Strong references are required by asyncio while an HTTP request returns an
# in-progress receipt.  Redis remains the cross-process lock/result transport;
# this registry only keeps the owning process's producer alive until it writes
# that result.
_OPERATION_TASKS: dict[str, asyncio.Task[Any]] = {}
_OPERATION_STARTED: dict[str, float] = {}


def retained_operation_progress(key: str) -> dict[str, Any]:
    """Return safe timing/stage metadata for an in-process retained task."""
    task = _OPERATION_TASKS.get(key)
    started = _OPERATION_STARTED.get(key)
    chain: list[str] = []
    current = task.get_coro() if task is not None else None
    for _ in range(12):
        if current is None:
            break
        code = getattr(current, "cr_code", None) or getattr(current, "gi_code", None)
        if code is not None:
            name = str(getattr(code, "co_name", "") or "")
            if name and name not in chain:
                chain.append(name)
        current = (
            getattr(current, "cr_await", None)
            or getattr(current, "gi_yieldfrom", None)
            or getattr(current, "ag_await", None)
        )
    return {
        "status": "running" if task is not None and not task.done() else "not_running",
        "elapsed_ms": round((time.monotonic() - started) * 1000) if started else None,
        "stage": chain[-1] if chain else None,
        "await_chain": chain,
    }


def retained_operation_task(
    key: str,
    producer: Callable[[], Awaitable[Any]],
) -> tuple[asyncio.Task[Any], bool]:
    """Return the one process-local producer and whether this caller created it."""
    current = _OPERATION_TASKS.get(key)
    if current is not None and not current.done():
        return current, False
    task = asyncio.create_task(producer(), name=f"chat-operation:{key[-32:]}")
    _OPERATION_TASKS[key] = task
    _OPERATION_STARTED[key] = time.monotonic()

    def release(completed: asyncio.Task[Any]) -> None:
        # Consume and identify failures which happen after the initiating HTTP
        # request has already returned an in-progress receipt.
        if not completed.cancelled():
            try:
                failure = completed.exception()
            except asyncio.CancelledError:
                failure = None
            if failure is not None:
                logging.getLogger("shopsquire.chat.transport").error(
                    "retained chat operation failed key=%s error=%s",
                    key[-48:], failure.__class__.__name__,
                )
        if _OPERATION_TASKS.get(key) is completed:
            _OPERATION_TASKS.pop(key, None)
            _OPERATION_STARTED.pop(key, None)

    task.add_done_callback(release)
    return task, True


async def idempotent_single_flight(
    redis, key: str, producer: Callable[[], Awaitable[Any]], *,
    wait_timeout_seconds: float = 2.0,
    in_progress_factory: Callable[[str], Any] | None = None,
    error_factory: Callable[[str, Exception], Any] | None = None,
    logger: logging.Logger | None = None,
) -> Any:
    """Cache one result and prevent a stream/query fallback from double-producing it."""
    log = logger or logging.getLogger("shopsquire.chat.transport")
    result_key, lock_key = key + ":result", key + ":lock"
    token = str(uuid.uuid4())
    try:
        cached = redis.get(result_key)
    except Exception:
        cached = None
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    try:
        claimed = bool(redis.set(lock_key, token, nx=True, ex=90))
    except Exception:
        claimed = True
    if not claimed:
        deadline = time.monotonic() + max(0.0, min(float(wait_timeout_seconds or 0.0), 10.0))
        while time.monotonic() < deadline:
            await asyncio.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            try:
                cached = redis.get(result_key)
            except Exception:
                cached = None
            if cached:
                try:
                    return json.loads(cached)
                except Exception:
                    break
        if in_progress_factory is not None:
            # The operation id is stable across SSE and query fallback calls. The
            # caller can retrieve the completed envelope by repeating the request
            # with this same idempotency key; no second orchestration is started.
            return in_progress_factory(key.rsplit(":", 1)[-1])
    try:
        try:
            result = await producer()
        except Exception as exc:
            if error_factory is None:
                raise
            log.exception("single-flight producer failed key=%s", key[-48:])
            result = error_factory(key.rsplit(":", 1)[-1], exc)
        try:
            redis.setex(result_key, 120, json.dumps(result, default=str))
        except Exception as exc:
            log.debug("idem result cache skipped: %s", repr(exc)[:80])
        return result
    finally:
        try:
            held = redis.get(lock_key)
            held = held.decode() if isinstance(held, bytes) else held
            if held == token:
                redis.delete(lock_key)
        except Exception as exc:
            log.debug("idem lock release skipped: %s", repr(exc)[:80])


__all__ = [
    "idempotent_single_flight", "retained_operation_task",
    "retained_operation_progress",
]
