from __future__ import annotations

import json
import inspect
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional


@dataclass
class AgentMessage:
    source_agent: str
    target_agent: Optional[str]
    message_type: str
    payload: dict
    trace_id: str
    timestamp: str


class AgentBus:
    """Event bus for agent-to-agent communication (Redis pub/sub)."""

    def __init__(self, redis_client):
        self.redis = redis_client

    async def publish(self, message: AgentMessage):
        channel = f"agent:{message.target_agent or 'broadcast'}"
        result = self.redis.publish(channel, json.dumps(message.__dict__))
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
