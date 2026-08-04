"""Redis Streams-based background task runner.

Replaces ad-hoc ``threading.Thread(daemon=True)`` calls scattered across
main.py and service modules.  Each task is published to a Redis stream
and consumed by a dedicated worker loop that:

  * Survives process restarts (pending entries are re-consumed via XREADGROUP)
  * Can be monitored (XINFO GROUPS / XLEN)
  * Does not silently die on OOM

When Redis is unavailable, falls back to an in-process thread pool with
a bounded queue and proper error logging — an improvement over bare daemon
threads.

Usage from application code::

    from src.app.workers.task_runner import submit_task

    submit_task("cv_warmup", {})
    submit_task("vs_index_build", {"limit": 50000})
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

_log = logging.getLogger("shopsquire.task_runner")

# ── Task registry: name → handler function ──
_HANDLERS: Dict[str, Callable[[Dict[str, Any]], None]] = {}

# Stream / consumer group constants
STREAM_NAME = os.getenv("TASK_STREAM_NAME", "shopsquire:tasks")
GROUP_NAME = os.getenv("TASK_CONSUMER_GROUP", "task-workers")
CONSUMER_NAME = os.getenv("TASK_CONSUMER_NAME", f"worker-{os.getpid()}")
DEAD_LETTER_STREAM = os.getenv("TASK_DEAD_LETTER_STREAM", f"{STREAM_NAME}:dead")

_consumer_thread: Optional[threading.Thread] = None
_shutdown_event = threading.Event()

# Fallback thread pool (bounded) for when Redis is unavailable
_fallback_pool: Optional[ThreadPoolExecutor] = None
_FALLBACK_POOL_SIZE = max(1, int(os.getenv("TASK_FALLBACK_POOL_SIZE", "3") or 3))
_fallback_slots: Optional[threading.BoundedSemaphore] = None


def _fallback_allowed() -> bool:
    explicit = os.getenv("TASK_ALLOW_INPROCESS_FALLBACK")
    if explicit is not None:
        return str(explicit).strip().lower() in ("1", "true", "yes", "on")
    app_env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return app_env in ("local", "dev", "development", "test", "testing")


def register_handler(task_name: str, handler: Callable[[Dict[str, Any]], None]) -> None:
    """Register a handler function for a task name."""
    _HANDLERS[task_name] = handler


def _get_redis():
    """Best-effort Redis client; returns None when unavailable."""
    try:
        from src.app.deps import get_redis
        r = get_redis()
        if r is None:
            return None
        r.ping()
        return r
    except Exception:
        return None


def submit_task(task_name: str, payload: Dict[str, Any] | None = None) -> str:
    """Submit a background task.  Returns a task ID.

    If Redis is available, the task is published to a stream.
    Otherwise it is executed via the in-process fallback pool.
    """
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    msg = {
        "task_id": task_id,
        "task_name": task_name,
        "payload": json.dumps(payload or {}),
        "submitted_at": time.time(),
    }

    redis = _get_redis()
    if redis is not None:
        try:
            redis.xadd(STREAM_NAME, msg, maxlen=10_000)
            _log.debug("task submitted to redis stream: %s [%s]", task_name, task_id)
            return task_id
        except Exception:
            _log.warning("redis xadd failed, using fallback pool", exc_info=True)

    if not _fallback_allowed():
        raise RuntimeError("durable_task_backend_unavailable")

    # Development fallback: bounded in-process thread pool.
    _execute_in_fallback_pool(task_name, payload or {}, task_id)
    return task_id


def _execute_in_fallback_pool(task_name: str, payload: Dict[str, Any], task_id: str) -> None:
    global _fallback_pool, _fallback_slots
    if _fallback_pool is None:
        _fallback_pool = ThreadPoolExecutor(
            max_workers=_FALLBACK_POOL_SIZE,
            thread_name_prefix="shopsquire-bg",
        )
        queue_size = max(
            0,
            int(os.getenv("TASK_FALLBACK_QUEUE_SIZE", "20") or 20),
        )
        _fallback_slots = threading.BoundedSemaphore(
            max(1, _FALLBACK_POOL_SIZE + queue_size)
        )
    slots = _fallback_slots
    if slots is None or not slots.acquire(blocking=False):
        raise RuntimeError("task_fallback_queue_full")

    def _run():
        handler = _HANDLERS.get(task_name)
        if handler is None:
            _log.warning("no handler registered for task %s", task_name)
            return
        try:
            handler(payload)
            _log.info("fallback task completed: %s [%s]", task_name, task_id)
        except Exception:
            _log.error("fallback task failed: %s [%s]", task_name, task_id, exc_info=True)

    try:
        future = _fallback_pool.submit(_run)
        future.add_done_callback(lambda _future: slots.release())
    except Exception:
        slots.release()
        _log.error("fallback pool rejected task: %s", task_name, exc_info=True)
        raise


# ── Stream consumer loop ──

def _field(fields: Dict[Any, Any], name: str, default: str = "") -> str:
    value = fields.get(name)
    if value is None:
        value = fields.get(name.encode("utf-8"))
    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _max_attempts() -> int:
    try:
        return max(1, min(int(os.getenv("TASK_MAX_ATTEMPTS", "3") or 3), 20))
    except (TypeError, ValueError):
        return 3


def _publish_failure(
    redis,
    *,
    msg_id: str,
    task_name: str,
    task_id: str,
    raw_payload: str,
    attempts: int,
    error: str,
    terminal: bool,
) -> bool:
    target = DEAD_LETTER_STREAM if terminal else STREAM_NAME
    fields = {
        "task_id": task_id,
        "task_name": task_name,
        "payload": raw_payload,
        "attempts": attempts,
        "original_message_id": msg_id,
        "last_error": error[:500],
        "failed_at": time.time(),
    }
    try:
        redis.xadd(target, fields, maxlen=10_000)
        return True
    except Exception:
        _log.error(
            "task failure could not be persisted: %s [%s]",
            task_name,
            task_id,
            exc_info=True,
        )
        return False


def _process_message(msg_id: str, fields: Dict[Any, Any], redis) -> None:
    """Process a single message from the stream."""
    task_name = _field(fields, "task_name")
    task_id = _field(fields, "task_id")
    raw_payload = _field(fields, "payload", "{}")
    try:
        attempts = max(0, int(_field(fields, "attempts", "0") or 0))
    except (TypeError, ValueError):
        attempts = 0

    handler = _HANDLERS.get(task_name)
    if handler is None:
        _log.error("unknown task: %s [%s], dead-lettering", task_name, task_id)
        persisted = _publish_failure(
            redis,
            msg_id=msg_id,
            task_name=task_name,
            task_id=task_id,
            raw_payload=raw_payload,
            attempts=attempts + 1,
            error="unknown_task",
            terminal=True,
        )
        if persisted:
            redis.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    try:
        payload = json.loads(raw_payload)
        handler(payload)
        _log.info("task completed: %s [%s]", task_name, task_id)
    except Exception as exc:
        _log.error("task failed: %s [%s]", task_name, task_id, exc_info=True)
        next_attempt = attempts + 1
        persisted = _publish_failure(
            redis,
            msg_id=msg_id,
            task_name=task_name,
            task_id=task_id,
            raw_payload=raw_payload,
            attempts=next_attempt,
            error=repr(exc),
            terminal=next_attempt >= _max_attempts(),
        )
        if persisted:
            redis.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return
    redis.xack(STREAM_NAME, GROUP_NAME, msg_id)


def _recover_pending(redis) -> int:
    """Claim stale pending deliveries so a crashed consumer cannot stall them."""
    try:
        min_idle_ms = max(
            1_000,
            int(os.getenv("TASK_PENDING_MIN_IDLE_MS", "60000") or 60_000),
        )
    except (TypeError, ValueError):
        min_idle_ms = 60_000
    result = redis.xautoclaim(
        STREAM_NAME,
        GROUP_NAME,
        CONSUMER_NAME,
        min_idle_ms,
        start_id="0-0",
        count=5,
    )
    messages = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else []
    recovered = 0
    for msg_id, fields in messages or []:
        _process_message(msg_id, fields, redis)
        recovered += 1
    return recovered


def _consumer_loop() -> None:
    """Blocking loop that reads tasks from the Redis stream."""
    _log.info("task consumer starting: stream=%s group=%s consumer=%s", STREAM_NAME, GROUP_NAME, CONSUMER_NAME)

    redis = _get_redis()
    if redis is None:
        _log.warning("task consumer: redis unavailable, exiting consumer loop")
        return

    # Ensure consumer group exists
    try:
        redis.xgroup_create(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)
    except Exception:
        pass  # group already exists

    last_recovery = 0.0
    while not _shutdown_event.is_set():
        try:
            recovery_interval = max(
                5.0,
                float(os.getenv("TASK_PENDING_RECOVERY_INTERVAL_SEC", "30") or 30),
            )
            now = time.monotonic()
            if now - last_recovery >= recovery_interval:
                try:
                    recovered = _recover_pending(redis)
                    if recovered:
                        _log.warning("recovered %s stale pending task(s)", recovered)
                except Exception:
                    _log.warning("pending task recovery failed", exc_info=True)
                last_recovery = now
            entries = redis.xreadgroup(
                GROUP_NAME, CONSUMER_NAME,
                {STREAM_NAME: ">"},
                count=5,
                block=2000,
            )
            if not entries:
                continue
            for _stream, messages in entries:
                for msg_id, fields in messages:
                    _process_message(msg_id, fields, redis)
        except Exception:
            if not _shutdown_event.is_set():
                _log.warning("task consumer error, retrying in 5s", exc_info=True)
                _shutdown_event.wait(5)

    _log.info("task consumer stopped")


def _task_consumer_enabled() -> bool:
    """Mirror trace_broker._redis_stream_enabled. The Redis Streams task consumer is OFF in
    local/dev/test — there, a blocking ``xreadgroup`` against an empty/unavailable stream just
    churns timeouts and leaks half-closed sockets (CLOSE_WAIT pileup → wedged port). It auto-enables
    in non-dev when REDIS_URL is configured. Explicit ``TASK_CONSUMER_ENABLED`` always wins."""
    raw = os.getenv("TASK_CONSUMER_ENABLED")
    if raw is not None:
        return str(raw).lower() in ("1", "true", "yes")
    app_env = str(os.getenv("APP_ENV", "local") or "local").lower()
    if app_env in ("local", "dev", "development", "test", "testing"):
        return False
    return bool(os.getenv("REDIS_URL"))


def start_consumer() -> None:
    """Start the Redis stream consumer in a background thread (no-op when disabled — see
    _task_consumer_enabled). Self-gating keeps the app-lifespan call site unconditional + simple."""
    if not _task_consumer_enabled():
        _log.info("task consumer disabled (TASK_CONSUMER_ENABLED unset in local/dev/test) — skipping")
        return
    global _consumer_thread
    if _consumer_thread is not None and _consumer_thread.is_alive():
        return
    _shutdown_event.clear()
    _consumer_thread = threading.Thread(target=_consumer_loop, daemon=True, name="task-consumer")
    _consumer_thread.start()


def stop_consumer() -> None:
    """Signal the consumer loop to stop gracefully."""
    _shutdown_event.set()
    if _consumer_thread is not None:
        _consumer_thread.join(timeout=10)


def shutdown_fallback_pool() -> None:
    """Clean shutdown of the in-process fallback pool."""
    global _fallback_pool, _fallback_slots
    if _fallback_pool is not None:
        _fallback_pool.shutdown(wait=False)
        _fallback_pool = None
        _fallback_slots = None
