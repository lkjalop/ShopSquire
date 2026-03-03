from src.app.security.firewall import TransactionFirewall
from src.app.services.orchestrator import Orchestrator


class _DummyMemory:
    def get_context(self, uid: str):
        return {"summary": None, "kv": None, "recent_retrieval": None}


def test_adaptive_budget_scales_for_complex_risky_query():
    orch = Orchestrator(memory=_DummyMemory(), firewall=TransactionFirewall({}), flags={})
    out = orch._compute_adaptive_agent_budgets(
        query="compare and explain detailed tradeoff for risky refund",
        tier=2,
        base_tool_budget=4,
        risk_adj=60.0,
        intent_confidence=0.62,
        multi_turn=True,
    )
    assert int(out.get("global_tool_budget") or 0) >= 5
    assert len((out.get("agent_tool_budgets") or {}).keys()) >= 5
    assert len((out.get("agent_token_budgets") or {}).keys()) >= 5


def test_step_slo_breach_marks_trace_degraded():
    orch = Orchestrator(
        memory=_DummyMemory(),
        firewall=TransactionFirewall({}),
        flags={"AGENT_STEP_SLO_MS_MAP": "CV_Label_Agent:1"},
    )
    trace_id = "trace-slo-1"
    orch._init_trace_runtime(trace_id)
    orch._trace_agent_invocation(
        trace_id,
        phase="phase2",
        agent_name="CV_Label_Agent",
        start_ms=0.0,
        end_ms=0.050,
        tags=["unit"],
        tool_budget_remaining=1,
    )
    assert orch._trace_is_degraded(trace_id) is True
    assert "step_slo_breach" in orch._trace_degrade_reasons(trace_id)

