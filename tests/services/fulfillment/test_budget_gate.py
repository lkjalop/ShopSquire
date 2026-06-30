"""Enterprise budget gate — a spend that breaches the category budget is flagged/blocked."""
from __future__ import annotations

import pytest

from src.app.services.fulfillment import budget_gate


def test_no_cap_is_always_within_budget(monkeypatch):
    monkeypatch.setattr(budget_gate, "_cap_for", lambda category: None)
    s = budget_gate.budget_status(99999999, category="gaming")
    assert s["within_budget"] is True and s["cap_cents"] is None


def test_within_and_over_cap(monkeypatch):
    monkeypatch.setattr(budget_gate, "_cap_for", lambda category: 1000000)  # $10,000 cap
    within = budget_gate.budget_status(300000, category="office")           # $3,000
    assert within["within_budget"] is True and within["remaining_cents"] == 1000000
    over = budget_gate.budget_status(1200000, category="office")            # $12,000 > $10,000
    assert over["within_budget"] is False and "exceeds remaining" in over["reason"]


def test_committed_spend_reduces_remaining(monkeypatch):
    monkeypatch.setattr(budget_gate, "_cap_for", lambda category: 1000000)  # $10,000 cap
    # $9,000 already committed → only $1,000 left; a $3,000 purchase breaches it
    s = budget_gate.budget_status(300000, category="office", committed_cents=900000)
    assert s["within_budget"] is False and s["remaining_cents"] == 100000


def test_bad_input_is_safe(monkeypatch):
    monkeypatch.setattr(budget_gate, "_cap_for", lambda category: 1000000)
    s = budget_gate.budget_status("oops", category="office", committed_cents=None)
    assert s["spend_cents"] == 0 and s["within_budget"] is True


def test_cumulative_two_cases_breach_one_cap(monkeypatch):
    """Review fix #5: two $6k cases under a $10k cap must NOT both pass — the second sees the first as
    committed and is blocked. (The router supplies committed_cents from prior committed cases in the category.)"""
    monkeypatch.setattr(budget_gate, "_cap_for", lambda category: 1000000)  # $10,000 cap
    first = budget_gate.budget_status(600000, category="it", committed_cents=0)        # $6k, nothing prior
    assert first["within_budget"] is True
    second = budget_gate.budget_status(600000, category="it", committed_cents=600000)  # $6k + $6k committed
    assert second["within_budget"] is False  # 12k > 10k
