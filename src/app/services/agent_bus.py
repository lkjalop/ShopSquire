from __future__ import annotations

import json
import inspect
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional
from pathlib import Path

try:
    import yaml
except Exception:
    yaml = None


@dataclass
class AgentMessage:
    source_agent: str
    target_agent: Optional[str]
    message_type: str
    payload: dict
    trace_id: str
    timestamp: str


_TAG_ROUTE_CACHE_LOCK = threading.Lock()
_TAG_ROUTE_CACHE: dict = {"mtime": None, "routes": {}}


def _tag_routes_path() -> Path:
    return Path("config") / "tag_routes.yml"


def _load_tag_routes() -> dict:
    path = _tag_routes_path()
    with _TAG_ROUTE_CACHE_LOCK:
        mtime = None
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = None
        if _TAG_ROUTE_CACHE.get("mtime") == mtime and isinstance(_TAG_ROUTE_CACHE.get("routes"), dict):
            return dict(_TAG_ROUTE_CACHE.get("routes") or {})
        routes: dict = {}
        try:
            if path.exists() and yaml is not None:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                routes = raw.get("tag_routes") if isinstance(raw.get("tag_routes"), dict) else {}
        except Exception:
            routes = {}
        _TAG_ROUTE_CACHE["mtime"] = mtime
        _TAG_ROUTE_CACHE["routes"] = routes
        return dict(routes)


class AgentBus:
    """Event bus for agent-to-agent communication (Redis pub/sub)."""

    def __init__(self, redis_client):
        self.redis = redis_client

    def resolve_targets(self, tags: list[str] | None) -> list[str]:
        routes = _load_tag_routes()
        out: list[str] = []
        for tag in tags or []:
            vals = routes.get(str(tag)) if isinstance(routes.get(str(tag)), list) else []
            for v in vals:
                t = str(v or "").strip()
                if t:
                    out.append(t)
        return list(dict.fromkeys(out))

    async def publish(self, message: AgentMessage):
        payload = json.dumps(message.__dict__)
        channels = []
        if message.target_agent:
            channels = [f"agent:{message.target_agent}"]
        else:
            signal_tags = []
            try:
                if isinstance(message.payload, dict):
                    signal_tags = [str(x) for x in (message.payload.get("signal_tags") or []) if x]
            except Exception:
                signal_tags = []
            routed = [f"agent:{name}" for name in self.resolve_targets(signal_tags)]
            channels = routed or ["agent:broadcast"]
        for channel in channels:
            result = self.redis.publish(channel, payload)
            if inspect.isawaitable(result):
                await result
        await self._log_to_trace(message)

    async def subscribe(self, agent_name: str, handler: Callable):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"agent:{agent_name}", "agent:broadcast")
        async for message in pubsub.listen():
            if message.get("type") == "message":
                raw = message.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                data = json.loads(raw)
                await handler(AgentMessage(**data))

    async def _log_to_trace(self, message: AgentMessage):
        from src.app.services.decision_log import log_trace_event
        log_trace_event(
            trace_id=message.trace_id,
            event_type="agent_communication",
            source_type="agent",
            source_id=message.source_agent,
            target_type="agent" if message.target_agent else "broadcast",
            target_id=message.target_agent,
            payload=message.payload,
        )


def build_agent_message(
    source_agent: str,
    target_agent: Optional[str],
    message_type: str,
    payload: dict,
    trace_id: str,
) -> AgentMessage:
    return AgentMessage(
        source_agent=source_agent,
        target_agent=target_agent,
        message_type=message_type,
        payload=payload,
        trace_id=trace_id,
        timestamp=datetime.utcnow().isoformat(),
    )
