"""LLM intent-planner fallback — governed + agnostic. With the LLM mocked, prove: it fires only on
low-confidence plans, validates/clamps the output to the store vocabulary, merges only into gaps
(never overrides confident rule extractions), and high-confidence queries bypass it entirely.
"""
from __future__ import annotations

import json

from src.app.services import llm_planner as lp
from src.app.services.query_decomposer import decompose


# ── low-confidence gate ──────────────────────────────────────────────────────
def test_low_confidence_only_when_rules_extract_nothing_on_nontrivial_query():
    # rules nail this → NOT low-confidence
    assert lp.is_low_confidence(decompose("gaming laptop under $1500")) is False
    # short/trivial → leave to rules
    assert lp.is_low_confidence(decompose("hi there")) is False
    # non-trivial but rules got nothing → low-confidence (fallback eligible)

    class _P:
        query = "the thing for doing my stuff that everyone keeps raving about lately"
        category = None
        use_cases: list = []
    assert lp.is_low_confidence(_P()) is True


# ── validation: whitelist + vocabulary clamp ─────────────────────────────────
def _llm(payload):
    return lambda prompt, timeout: json.dumps(payload)


def test_validate_clamps_to_profile_vocab_and_whitelist(monkeypatch):
    monkeypatch.setattr(lp, "_profile_vocab", lambda pid=None: (["laptop", "monitor"], ["gaming", "office"]))
    # valid category+use_cases within vocab; bogus ones dropped; budget coerced
    out = lp.plan_with_llm("x y z w", llm_fn=_llm({
        "intent": "product_search", "category": "laptop", "use_cases": ["gaming", "WIDGET"],
        "budget_max": 1500, "quantity": 3, "evil": "drop me",
    }))
    assert out == {"intent": "product_search", "category": "laptop", "use_cases": ["gaming"],
                   "budget_max": 1500, "quantity": 3}


def test_validate_rejects_out_of_vocab_category_and_bad_intent(monkeypatch):
    monkeypatch.setattr(lp, "_profile_vocab", lambda pid=None: (["laptop"], ["gaming"]))
    out = lp.plan_with_llm("x y z w", llm_fn=_llm({"intent": "launch_missiles", "category": "yacht"}))
    assert out is None  # nothing valid survived


def test_plan_with_llm_returns_none_on_garbage(monkeypatch):
    monkeypatch.setattr(lp, "_profile_vocab", lambda pid=None: (["laptop"], ["gaming"]))
    assert lp.plan_with_llm("x y z w", llm_fn=lambda p, t: "not json at all") is None


# ── merge: fills gaps only, never overrides confident rules ───────────────────
def test_merge_fills_gaps_only():
    plan = decompose("something nobody can parse here please")  # low-confidence, category/use_cases empty
    filled = lp.merge_llm_plan(plan, {"category": "laptop", "use_cases": ["office"], "budget_max": 1200})
    assert plan.category == "laptop" and plan.use_cases == ["office"] and plan.budget_max == 1200
    assert set(filled) >= {"category", "use_cases", "budget_max"}


def test_merge_never_overrides_confident_rule_extraction():
    plan = decompose("gaming laptop under $1500")  # rules set category/use_cases/budget
    before = (plan.category, list(plan.use_cases), plan.budget_max)
    lp.merge_llm_plan(plan, {"category": "monitor", "use_cases": ["office"], "budget_max": 9999})
    assert (plan.category, list(plan.use_cases), plan.budget_max) == before  # unchanged


def test_disabled_by_default():
    import os
    os.environ.pop("LLM_PLANNER_ENABLED", None)
    assert lp.llm_planner_enabled() is False
