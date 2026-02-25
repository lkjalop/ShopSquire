from __future__ import annotations

from src.app.services.interleaving_controller import InterleavingController, StopReason


def test_interleaving_budget_exhausted_sets_hitl_flags():
    c = InterleavingController(agent_type="orchestrator", tool_budget=0)
    c.start()
    c.should_continue()
    assert c.state.stop_reason == StopReason.BUDGET_EXHAUSTED
    s = c.get_summary()
    assert s.get("needs_human_review") is True
    assert s.get("escalation_reason") == "budget_exhausted"
