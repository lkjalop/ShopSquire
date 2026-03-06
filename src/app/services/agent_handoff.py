from __future__ import annotations

import asyncio
from typing import Dict

from src.app.services.agent_bus import AgentBus, build_agent_message
from src.app.services.decision_log import log_trace_event


class AgentHandoff:
    """Manage handoffs between agents via AgentBus."""

    def __init__(self, bus: AgentBus):
        self.bus = bus

    async def request_handoff(
        self,
        from_agent: str,
        to_agent: str | None,
        reason: str,
        context: dict,
        trace_id: str,
    ) -> Dict:
        targets = [to_agent] if to_agent else self.bus.resolve_targets((context or {}).get("signal_tags") or [])
        if not targets:
            targets = ["broadcast"]
        log_trace_event(
            trace_id=trace_id,
            event_type="handoff_requested",
            source_type="agent",
            source_id=from_agent,
            target_type="agent",
            target_id=targets[0],
            payload={"reason": reason, "context_keys": list(context.keys()), "targets": targets},
        )
        for target in targets:
            await self.bus.publish(
                build_agent_message(
                    source_agent=from_agent,
                    target_agent=None if target == "broadcast" else target,
                    message_type="handoff_request",
                    payload={"reason": reason, "context": context, "signal_tags": (context or {}).get("signal_tags") or []},
                    trace_id=trace_id,
                )
            )
        return {"status": "handoff_requested", "to_agent": to_agent, "targets": targets}


def request_handoff_best_effort(
    *,
    bus: AgentBus | None,
    from_agent: str,
    to_agent: str | None,
    reason: str,
    context: dict,
    trace_id: str,
) -> Dict:
    """Run AgentHandoff with trace-first semantics even without a bus.

    Always emits a handoff_requested trace event. If a bus is available,
    it will publish; otherwise returns trace-only status.
    """
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="handoff_requested",
            source_type="agent",
            source_id=from_agent,
            target_type="agent",
            target_id=to_agent,
            payload={"reason": reason, "context_keys": list((context or {}).keys())},
        )
    except Exception:
        pass
    if bus is None:
        return {"status": "trace_only", "to_agent": to_agent}
    try:
        handoff = AgentHandoff(bus=bus)
        coro = handoff.request_handoff(
            from_agent=from_agent,
            to_agent=to_agent,
            reason=reason,
            context=context,
            trace_id=trace_id,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
                # Running loop context: schedule publish as a background task
                try:
                    asyncio.get_running_loop().create_task(coro)
                    return {"status": "scheduled", "to_agent": to_agent}
                except Exception:
                    # if scheduling failed, return trace-only but keep trace event emitted
                    return {"status": "trace_only", "to_agent": to_agent}
        return asyncio.run(coro)
    except Exception:
        return {"status": "failed", "to_agent": to_agent}
