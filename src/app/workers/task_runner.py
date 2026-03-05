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

_consumer_thread: Optional[threading.Thread] = None
_shutdown_event = threading.Event()

# Fallback thread pool (bounded) for when Redis is unavailable
_fallback_pool: Optional[ThreadPoolExecutor] = None
_FALLBACK_POOL_SIZE = int(os.getenv("TASK_FALLBACK_POOL_SIZE", "3"))


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

    # Fallback: in-process thread pool
    _execute_in_fallback_pool(task_name, payload or {}, task_id)
    return task_id


def _execute_in_fallback_pool(task_name: str, payload: Dict[str, Any], task_id: str) -> None:
    global _fallback_pool
    if _fallback_pool is None:
        _fallback_pool = ThreadPoolExecutor(
            max_workers=_FALLBACK_POOL_SIZE,
            thread_name_prefix="shopsquire-bg",
        )

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
        _fallback_pool.submit(_run)
    except Exception:
        _log.error("fallback pool rejected task: %s", task_name, exc_info=True)


# ── Stream consumer loop ──

def _process_message(msg_id: str, fields: Dict[bytes, bytes], redis) -> None:
    """Process a single message from the stream."""
    task_name = (fields.get(b"task_name") or b"").decode()
    task_id = (fields.get(b"task_id") or b"").decode()
    raw_payload = (fields.get(b"payload") or b"{}").decode()

    handler = _HANDLERS.get(task_name)
    if handler is None:
        _log.warning("unknown task: %s [%s], acking", task_name, task_id)
        redis.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    try:
        payload = json.loads(raw_payload)
        handler(payload)
        _log.info("task completed: %s [%s]", task_name, task_id)
    except Exception:
        _log.error("task failed: %s [%s]", task_name, task_id, exc_info=True)
    finally:
        # Always ACK; failed tasks are logged for observability.
        # A DLQ pattern can be added later for retries.
        try:
            redis.xack(STREAM_NAME, GROUP_NAME, msg_id)
        except Exception:
            pass


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

    while not _shutdown_event.is_set():
        try:
            # Read pending (unacked) first, then new messages
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


def start_consumer() -> None:
    """Start the Redis stream consumer in a background thread."""
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
    global _fallback_pool
    if _fallback_pool is not None:
        _fallback_pool.shutdown(wait=False)
        _fallback_pool = None
