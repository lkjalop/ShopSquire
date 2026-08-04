"""Unit tests for the extracted adaptive agent-budget math (services/agent_budgets.py).

Characterizes the behaviour that was previously buried in the orchestrator, so the budget logic is
pinned independently of the route. Pure function — no app/DB.
"""
from __future__ import annotations

from src.app.services.agent_budgets import compute_adaptive_agent_budgets

_FLAGS = {"AGENT_TOKEN_BUDGET_DEFAULT": 2200}


def _budgets(**kw):
    base = dict(query="laptop", tier=1, base_tool_budget=4, risk_adj=0.0,
                intent_confidence=1.0, multi_turn=False, flags=_FLAGS)
    base.update(kw)
    return compute_adaptive_agent_budgets(**base)


def test_shape_and_global_budget_clamped():
    out = _budgets()
    assert set(out) == {"global_tool_budget", "factor", "complexity_hits",
                        "agent_tool_budgets", "agent_token_budgets"}
    assert 1 <= out["global_tool_budget"] <= 12  # clamped
    # per-agent allocations sum to the global budget (last agent gets the remainder).
    assert sum(out["agent_tool_budgets"].values()) == out["global_tool_budget"]


def test_complexity_hits_counted():
    assert _budgets(query="compare and explain the tradeoff")["complexity_hits"] >= 2


def test_factor_increases_with_tier_and_risk_and_low_confidence():
    base = _budgets()["factor"]
    assert _budgets(tier=2)["factor"] > base
    assert _budgets(risk_adj=50.0)["factor"] > base
    assert _budgets(intent_confidence=0.5)["factor"] > base
    assert _budgets(multi_turn=True)["factor"] > base


def test_event_signal_boosts_relevant_agents():
    base = _budgets(base_tool_budget=10)
    abandon = _budgets(base_tool_budget=10, event_signals={"cart_abandonment_detected": True})
    # cart abandonment boosts ranking; factor rises too.
    assert abandon["factor"] > base["factor"]
    coupon = _budgets(base_tool_budget=10, event_signals={"coupon_abuse_signals": True})
    assert coupon["factor"] > base["factor"]


def test_global_budget_never_below_one_or_above_twelve():
    assert _budgets(base_tool_budget=0)["global_tool_budget"] >= 1
    assert _budgets(base_tool_budget=100, tier=2, risk_adj=99.0,
                    intent_confidence=0.1, multi_turn=True,
                    query="compare explain why tradeoff")["global_tool_budget"] <= 12


def test_token_budgets_have_a_floor():
    out = _budgets()
    assert all(v >= 256 for v in out["agent_token_budgets"].values())
