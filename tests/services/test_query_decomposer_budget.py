"""Smarter, still-agnostic decomposition: budget is surfaced INTO the QueryPlan via an agnostic
numeric parse (no vertical literals), and the GPU model hint now reads gpu_prefixes from the active
profile (electronics stays byte-identical; other verticals add none).
"""
from __future__ import annotations

from src.app.services.query_decomposer import decompose


def test_budget_range_surfaced_into_plan():
    plan = decompose("gaming laptop between $1200 and $1800")
    assert plan.budget_min == 1200
    assert plan.budget_max == 1800
    d = plan.to_dict()
    assert d["budget_min"] == 1200 and d["budget_max"] == 1800


def test_budget_under_max_only():
    plan = decompose("a laptop under $1500")
    assert plan.budget_min is None
    assert plan.budget_max == 1500


def test_budget_over_min_only():
    plan = decompose("something over 2000 dollars please")
    assert plan.budget_min == 2000
    assert plan.budget_max is None


def test_no_budget_is_none():
    plan = decompose("show me a laptop for gaming")
    assert plan.budget_min is None and plan.budget_max is None


def test_gpu_hint_still_profile_driven_electronics_byte_identical():
    # Default active profile is electronics → gpu_prefixes ["rtx","gtx","rx"]; hint matches as before.
    plan = decompose("rtx 4070 gaming laptop")
    assert plan.hard_constraints.get("gpu_model_hint") == "rtx 4070"
