"""Runtime boundary for incident-room delivery and staff presence.

Queues are deliberately local to an ASGI worker. Presence is mirrored to Redis when
available so UI status survives worker restarts and concurrent staff are represented
individually. Cross-worker event fan-out remains an explicit capability gap until a
Redis pub/sub subscriber is enrolled; callers can expose that truth instead of claiming
multi-instance delivery from process memory.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.app.deps import DummyRedis, get_redis


@dataclass
class IncidentConversationRuntime:
    subscribers: dict[str, list[asyncio.Queue]] = field(default_factory=lambda: defaultdict(list))
    local_presence: dict[str, dict[str, dict[str, Any]]] = field(default_factory=lambda: defaultdict(dict))
    _lock: threading.RLock = field(default_factory=threading.RLock)
    presence_ttl_seconds: int = 90
    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _listener_thread: threading.Thread | None = field(default=None, init=False)
    _listener_started: bool = field(default=False, init=False)

    def subscribe(self, incident_id: str) -> asyncio.Queue:
        self.ensure_broker_listener()
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self.subscribers[incident_id].append(queue)
        return queue

    def unsubscribe(self, incident_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            queues = self.subscribers.get(incident_id, [])
            if queue in queues:
                queues.remove(queue)
            if not queues:
                self.subscribers.pop(incident_id, None)

    def publish_local(self, incident_id: str, event: dict[str, Any]) -> None:
        self._deliver_local(incident_id, event)
        try:
            redis = get_redis()
            if not isinstance(redis, DummyRedis):
                redis.publish(
                    "shopsquire:incident_conversation",
                    json.dumps({"origin": self.instance_id, "incident_id": incident_id, "event": event}),
                )
        except Exception:
            pass

    def _deliver_local(self, incident_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            queues = list(self.subscribers.get(incident_id, []))
        for queue in queues:
            try:
                queue.put_nowait(event)
            except Exception:
                continue

    def ensure_broker_listener(self) -> bool:
        with self._lock:
            if self._listener_started:
                return True
            try:
                redis = get_redis()
                if isinstance(redis, DummyRedis) or not hasattr(redis, "pubsub"):
                    return False
                pubsub = redis.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe("shopsquire:incident_conversation")
            except Exception:
                return False
            self._listener_started = True

        def consume() -> None:
            try:
                for message in pubsub.listen():
                    try:
                        raw = message.get("data") if isinstance(message, dict) else None
                        envelope = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
                        if envelope.get("origin") == self.instance_id:
                            continue
                        incident_id = str(envelope.get("incident_id") or "")
                        event = envelope.get("event")
                        if incident_id and isinstance(event, dict):
                            self._deliver_local(incident_id, event)
                    except Exception:
                        continue
            finally:
                with self._lock:
                    self._listener_started = False

        self._listener_thread = threading.Thread(
            target=consume,
            name=f"incident-chat-{self.instance_id[:8]}",
            daemon=True,
        )
        self._listener_thread.start()
        return True

    def join(self, incident_id: str, actor: dict[str, Any]) -> bool:
        actor_id = str(actor.get("actor_id") or "staff:unknown")
        record = {**actor, "last_seen_at": int(time.time()), "presence": "online"}
        with self._lock:
            first = actor_id not in self.local_presence[incident_id]
            self.local_presence[incident_id][actor_id] = record
        self._write_redis_presence(incident_id, actor_id, record)
        return first

    def leave(self, incident_id: str, actor: dict[str, Any]) -> bool:
        actor_id = str(actor.get("actor_id") or "staff:unknown")
        with self._lock:
            existed = self.local_presence.get(incident_id, {}).pop(actor_id, None) is not None
            if not self.local_presence.get(incident_id):
                self.local_presence.pop(incident_id, None)
        self._remove_redis_presence(incident_id, actor_id)
        return existed

    def active_staff(self, incident_id: str) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        with self._lock:
            merged.update(self.local_presence.get(incident_id, {}))
        try:
            redis = get_redis()
            if not isinstance(redis, DummyRedis):
                raw = redis.get(self._presence_key(incident_id))
                if raw:
                    decoded = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
                    now = int(time.time())
                    for actor_id, record in dict(decoded).items():
                        if now - int(record.get("last_seen_at") or 0) <= self.presence_ttl_seconds:
                            merged[actor_id] = record
        except Exception:
            pass
        return sorted(merged.values(), key=lambda item: str(item.get("actor_id") or ""))

    @property
    def distribution_status(self) -> str:
        try:
            if isinstance(get_redis(), DummyRedis):
                return "process_local"
            return "redis_pubsub" if self.ensure_broker_listener() else "redis_presence_local_events"
        except Exception:
            return "process_local"

    @staticmethod
    def _presence_key(incident_id: str) -> str:
        return f"incident_chat_presence:{incident_id}"

    def _write_redis_presence(self, incident_id: str, actor_id: str, record: dict[str, Any]) -> None:
        try:
            redis = get_redis()
            if isinstance(redis, DummyRedis):
                return
            key = self._presence_key(incident_id)
            current = redis.get(key)
            values = json.loads(current.decode() if isinstance(current, bytes) else str(current)) if current else {}
            values[actor_id] = record
            redis.setex(key, self.presence_ttl_seconds, json.dumps(values))
        except Exception:
            pass

    def _remove_redis_presence(self, incident_id: str, actor_id: str) -> None:
        try:
            redis = get_redis()
            if isinstance(redis, DummyRedis):
                return
            key = self._presence_key(incident_id)
            current = redis.get(key)
            values = json.loads(current.decode() if isinstance(current, bytes) else str(current)) if current else {}
            values.pop(actor_id, None)
            if values:
                redis.setex(key, self.presence_ttl_seconds, json.dumps(values))
            else:
                redis.delete(key)
        except Exception:
            pass


INCIDENT_CONVERSATION_RUNTIME = IncidentConversationRuntime()
