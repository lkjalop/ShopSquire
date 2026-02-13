import asyncio
import os
import socket
import json
from typing import Optional
from typing import Dict, List, Any

_SUBSCRIBERS: Dict[str, List[asyncio.Queue]] = {}
_STREAM_TASK: Optional[asyncio.Task] = None
_STREAM_STOP = False
_REDIS_CLIENT = None
_LAST_RECOVERY_TS = 0.0


def _redis_stream_enabled() -> bool:
    raw = os.getenv("TRACE_BROKER_REDIS_STREAM_ENABLED")
    if raw is not None:
        return str(raw).lower() in ("1", "true", "yes")
    app_env = str(os.getenv("APP_ENV", "local") or "local").lower()
    if app_env in ("local", "dev", "development", "test", "testing"):
        return False
    # Auto-enable in non-dev when Redis is configured.
    return bool(os.getenv("REDIS_URL"))


def _stream_name() -> str:
    return os.getenv("TRACE_BROKER_STREAM_NAME", "trace_events")


def _stream_group() -> str:
    return os.getenv("TRACE_BROKER_STREAM_GROUP", "shopsquire_trace_fanout")


def _stream_consumer() -> str:
    host = socket.gethostname() or "node"
    return f"{host}-{os.getpid()}"


def _ensure_list(trace_id: str):
    if trace_id not in _SUBSCRIBERS:
        _SUBSCRIBERS[trace_id] = []
    return _SUBSCRIBERS[trace_id]


async def _redis() -> Any:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    try:
        import redis.asyncio as redis  # type: ignore
    except Exception:
        return None
    try:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _REDIS_CLIENT = redis.from_url(url, decode_responses=True)
        return _REDIS_CLIENT
    except Exception:
        return None


async def _ensure_group(client) -> None:
    if client is None:
        return
    try:
        await client.xgroup_create(_stream_name(), _stream_group(), id="0", mkstream=True)
    except Exception:
        # BUSYGROUP expected
        pass


async def _distribute_local(trace_id: str, event: Any) -> None:
    try:
        lst = list(_SUBSCRIBERS.get(trace_id) or [])
        for q in lst:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    _ = q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(event)
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass


async def _stream_consumer_loop() -> None:
    global _STREAM_STOP
    global _LAST_RECOVERY_TS
    _STREAM_STOP = False
    client = await _redis()
    if client is None:
        return
    await _ensure_group(client)
    while not _STREAM_STOP:
        try:
            try:
                recovery_every = float(os.getenv("TRACE_BROKER_RECOVERY_INTERVAL_SEC", "30") or 30)
            except Exception:
                recovery_every = 30.0
            now = asyncio.get_event_loop().time()
            if recovery_every > 0 and (now - float(_LAST_RECOVERY_TS)) >= recovery_every:
                _LAST_RECOVERY_TS = now
                try:
                    await recover_pending(max_messages=200)
                except Exception:
                    pass
            rows = await client.xreadgroup(
                groupname=_stream_group(),
                consumername=_stream_consumer(),
                streams={_stream_name(): ">"},
                count=100,
                block=1000,
            )
            if not rows:
                continue
            for _sname, messages in rows:
                for msg_id, fields in messages:
                    try:
                        trace_id = fields.get("trace_id")
                        payload_raw = fields.get("payload")
                        if not trace_id or not payload_raw:
                            await client.xack(_stream_name(), _stream_group(), msg_id)
                            continue
                        try:
                            event = json.loads(payload_raw)
                        except Exception:
                            event = {"trace_id": trace_id, "payload": payload_raw}
                        await _distribute_local(trace_id, event)
                        await client.xack(_stream_name(), _stream_group(), msg_id)
                    except Exception:
                        # leave pending for retry/claim
                        pass
        except Exception:
            await asyncio.sleep(0.25)


async def start_stream_consumer() -> None:
    global _STREAM_TASK
    if not _redis_stream_enabled():
        return
    if _STREAM_TASK is not None and not _STREAM_TASK.done():
        return
    loop = asyncio.get_event_loop()
    _STREAM_TASK = loop.create_task(_stream_consumer_loop())


async def stop_stream_consumer() -> None:
    global _STREAM_STOP
    _STREAM_STOP = True
    try:
        if _STREAM_TASK is not None:
            _STREAM_TASK.cancel()
    except Exception:
        pass


def subscribe(trace_id: str) -> asyncio.Queue:
    try:
        maxsize = int(os.getenv("TRACE_BROKER_QUEUE_MAX", "256") or 256)
    except Exception:
        maxsize = 256
    if maxsize < 0:
        maxsize = 0
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    _ensure_list(trace_id).append(q)
    return q


def unsubscribe(trace_id: str, q: asyncio.Queue) -> None:
    try:
        lst = _SUBSCRIBERS.get(trace_id) or []
        if q in lst:
            lst.remove(q)
        if not lst:
            _SUBSCRIBERS.pop(trace_id, None)
    except Exception:
        pass


async def publish(trace_id: str, event: Any) -> None:
    if _redis_stream_enabled():
        client = await _redis()
        if client is not None:
            try:
                await _ensure_group(client)
                payload = event
                try:
                    payload = json.dumps(event, ensure_ascii=False)
                except Exception:
                    payload = json.dumps({"trace_id": trace_id, "event": str(event)}, ensure_ascii=False)
                maxlen = int(os.getenv("TRACE_BROKER_STREAM_MAXLEN", "100000") or 100000)
                await client.xadd(
                    _stream_name(),
                    {"trace_id": trace_id, "payload": payload},
                    maxlen=maxlen,
                    approximate=True,
                )
            except Exception:
                # continue local fanout fallback
                pass
    # Always local fanout for same-process subscribers
    await _distribute_local(trace_id, event)


def publish_sync(trace_id: str, event: Any) -> None:
    """Synchronous best-effort publish for non-async contexts (tests).

    Mirrors the behavior of the async `publish` but runs synchronously
    to avoid creating an event loop or spawning threads for each call.
    """
    try:
        lst = list(_SUBSCRIBERS.get(trace_id) or [])
        for q in lst:
            try:
                q.put_nowait(event)
            except Exception:
                try:
                    _ = q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(event)
                except Exception:
                    pass
    except Exception:
        pass


async def stream_health() -> Dict[str, Any]:
    out = {"enabled": _redis_stream_enabled(), "stream": _stream_name(), "group": _stream_group(), "ok": False}
    if not out["enabled"]:
        return out
    client = await _redis()
    if client is None:
        out["error"] = "redis_unavailable"
        return out
    try:
        await _ensure_group(client)
        groups = await client.xinfo_groups(_stream_name())
        group = None
        for g in groups or []:
            name = g.get("name") if isinstance(g, dict) else None
            if name == _stream_group():
                group = g
                break
        out["ok"] = group is not None
        out["group_info"] = group or {}
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


async def recover_pending(*, max_messages: int = 100) -> Dict[str, Any]:
    out = {"recovered": 0, "acked": 0, "errors": 0}
    if not _redis_stream_enabled():
        out["status"] = "disabled"
        return out
    client = await _redis()
    if client is None:
        out["status"] = "redis_unavailable"
        return out
    try:
        await _ensure_group(client)
        rows = await client.xautoclaim(
            _stream_name(),
            _stream_group(),
            _stream_consumer(),
            min_idle_time=int(os.getenv("TRACE_BROKER_RECOVER_MIN_IDLE_MS", "30000") or 30000),
            start_id="0-0",
            count=max(1, min(int(max_messages or 100), 1000)),
        )
        messages = []
        try:
            messages = rows[1] if isinstance(rows, (list, tuple)) and len(rows) > 1 else []
        except Exception:
            messages = []
        for msg_id, fields in messages or []:
            try:
                trace_id = fields.get("trace_id")
                payload_raw = fields.get("payload")
                if trace_id and payload_raw:
                    try:
                        event = json.loads(payload_raw)
                    except Exception:
                        event = {"trace_id": trace_id, "payload": payload_raw}
                    await _distribute_local(trace_id, event)
                    out["recovered"] += 1
                await client.xack(_stream_name(), _stream_group(), msg_id)
                out["acked"] += 1
            except Exception:
                out["errors"] += 1
        return out
    except Exception as exc:
        out["status"] = "error"
        out["error"] = str(exc)
        return out


async def replay_recent(*, count: int = 100) -> Dict[str, Any]:
    out = {"replayed": 0, "errors": 0}
    if not _redis_stream_enabled():
        out["status"] = "disabled"
        return out
    client = await _redis()
    if client is None:
        out["status"] = "redis_unavailable"
        return out
    try:
        rows = await client.xrevrange(_stream_name(), count=max(1, min(int(count or 100), 2000)))
        for _msg_id, fields in rows or []:
            try:
                trace_id = fields.get("trace_id")
                payload_raw = fields.get("payload")
                if not trace_id or not payload_raw:
                    continue
                try:
                    event = json.loads(payload_raw)
                except Exception:
                    event = {"trace_id": trace_id, "payload": payload_raw}
                await _distribute_local(trace_id, event)
                out["replayed"] += 1
            except Exception:
                out["errors"] += 1
        return out
    except Exception as exc:
        out["status"] = "error"
        out["error"] = str(exc)
        return out
