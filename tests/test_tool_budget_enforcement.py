import asyncio
from src.app.services.agent_dag_runtime import run_exploration_dag
from src.app.services.interleaving_controller import InterleavingController, run_interleaved


def test_agent_dag_runtime_budget_short_circuit():
    """When budget is 0, DAG should short-circuit and set budget_skipped flag."""

    async def runner():
        res = await run_exploration_dag(
            payload={},
            run_security=lambda: {"ok": True},
            run_cv=lambda: {"ok": True},
            run_fraud=lambda: {"ok": True},
            run_inventory=lambda: {"ok": True},
            tenant_id=None,
            budget=0,
        )
        return res

    out = asyncio.run(runner())
    assert isinstance(out, dict)
    assert out.get("meta", {}).get("budget_skipped") is True


def test_interleaving_controller_respects_zero_budget():
    ctrl = InterleavingController(agent_type="orchestrator", max_iterations=3, tool_budget=0, confidence_threshold=0.9)

    def think_fn(state):
        return {"tool_name": "retrieve_context", "arguments": {}}

    def tool_fn(name, args):
        return {"status": "should_not_run"}

    def observe_fn(result, state):
        return 0.5

    summary = run_interleaved(ctrl, think_fn, tool_fn, observe_fn)
    assert isinstance(summary, dict)
    assert summary.get("budget_remaining") == 0
    assert summary.get("stop_reason") == "budget_exhausted"


def test_agent_dag_runtime_tool_intent_gate_blocks_denied_tool(monkeypatch):
    monkeypatch.setenv("GLOBAL_TOOL_INTENT_DENYLIST", "security_scan")

    async def runner():
        return await run_exploration_dag(
            payload={"trace_id": "trace-tool-gate-1"},
            run_security=lambda: {"ok": True},
            run_cv=lambda: {"ok": True},
            run_fraud=lambda: {"ok": True},
            run_inventory=lambda: {"ok": True},
            tenant_id="t1",
            budget=3,
        )

    out = asyncio.run(runner())
    assert isinstance(out, dict)
    sec = (out.get("phase1") or {}).get("security") or {}
    assert sec.get("_blocked") is True
    assert ((sec.get("gate") or {}).get("reason")) in ("tool_intent_denylist", "tool_intent_not_allowlisted", "policy_gate_review")
