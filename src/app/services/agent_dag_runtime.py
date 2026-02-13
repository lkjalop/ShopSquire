from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Dict
from src.app.security.tool_intent_gate import evaluate_tool_intent
from src.app.services.decision_log import log_trace_event


class TenantPoolManager:
    def __init__(self) -> None:
        self._defaults = {
            "nlp": int(os.getenv("AGENT_POOL_NLP", "3") or 3),
            "cv": int(os.getenv("AGENT_POOL_CV", "2") or 2),
            "fraud": int(os.getenv("AGENT_POOL_FRAUD", "3") or 3),
            "inventory": int(os.getenv("AGENT_POOL_INVENTORY", "5") or 5),
            "security": int(os.getenv("AGENT_POOL_SECURITY", "3") or 3),
        }

    def limits_for_tenant(self, _tenant_id: str | None) -> Dict[str, int]:
        # Hook for tier-specific overrides; defaults are stable and deterministic.
        return dict(self._defaults)


async def _call_with_limit(limit: int, fn: Callable[[], Any], timeout_sec: float = 2.5) -> Any:
    sem = asyncio.Semaphore(max(1, int(limit or 1)))
    async with sem:
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_sec)
        except Exception as exc:
            return {"_error": str(exc)}


async def _gated_call(
    *,
    limit: int,
    fn: Callable[[], Any],
    tool_name: str,
    payload: Dict[str, Any],
    tenant_id: str | None,
) -> Any:
    trace_id = str((payload or {}).get("trace_id") or "")
    gate = evaluate_tool_intent(
        tool_name=tool_name,
        params={"payload_keys": sorted(list((payload or {}).keys()))[:24]},
        runtime="agent_dag_runtime",
        tenant_id=tenant_id,
        trace_id=trace_id or None,
    )
    if not bool(gate.get("allow")):
        try:
            if trace_id:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="tool_policy_denied",
                    source_type="agent_dag_runtime",
                    source_id="ToolIntentGate",
                    target_type="tool",
                    target_id=tool_name,
                    payload=gate,
                )
        except Exception:
            pass
        return {"_blocked": True, "tool_name": tool_name, "gate": gate}
    return await _call_with_limit(limit, fn)


async def run_exploration_dag(
    *,
    payload: Dict[str, Any],
    run_security: Callable[[], Any],
    run_cv: Callable[[], Any],
    run_fraud: Callable[[], Any],
    run_inventory: Callable[[], Any],
    tenant_id: str | None = None,
    budget: int | None = None,
) -> Dict[str, Any]:
    pools = TenantPoolManager().limits_for_tenant(tenant_id)
    # If budget explicitly exhausted, skip expensive exploration and return placeholders
    if budget is not None and int(budget or 0) <= 0:
        return {
            "phase1": {"security": None, "cv": None},
            "phase2": {"fraud": None, "inventory": None},
            "meta": {"tenant_id": tenant_id, "dag_version": "v1", "budget_skipped": True},
        }

    # Phase 1: read-only exploration
    phase1 = await asyncio.gather(
        _gated_call(limit=pools.get("security", 1), fn=run_security, tool_name="security_scan", payload=payload, tenant_id=tenant_id),
        _gated_call(limit=pools.get("cv", 1), fn=run_cv, tool_name="cv_scan", payload=payload, tenant_id=tenant_id),
        return_exceptions=False,
    )
    # Phase 2: scored evaluation (can run in parallel after phase1 context exists)
    phase2 = await asyncio.gather(
        _gated_call(limit=pools.get("fraud", 1), fn=run_fraud, tool_name="fraud_scoring", payload=payload, tenant_id=tenant_id),
        _gated_call(limit=pools.get("inventory", 1), fn=run_inventory, tool_name="inventory_check", payload=payload, tenant_id=tenant_id),
        return_exceptions=False,
    )
    return {
        "phase1": {"security": phase1[0], "cv": phase1[1]},
        "phase2": {"fraud": phase2[0], "inventory": phase2[1]},
        "meta": {"tenant_id": tenant_id, "dag_version": "v1"},
    }
