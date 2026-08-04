"""Narration truthfulness (GPT-5.5 #1) — the claim guard reports its TRUE state and is on by default.

The bug: when the guard was disabled it was reported as "passed" (it never verified anything). Now it
records disabled/skipped/passed/fell_back_to_deterministic honestly, and blocking is default-ON
(rejecting an ungrounded claim only makes output more conservative).
"""
from __future__ import annotations

import os

from src.app.services.recommend_narration_stage import apply_product_claim_guard


class _GR:
    def __init__(self, grounded, violations=()):
        self.grounded = grounded
        self.violations = list(violations)


def _det(*a, **k):
    return "DETERMINISTIC FALLBACK"


def _run(enabled, grounded, msg="LLM prose", results=None):
    c: dict = {}
    out = apply_product_claim_guard(
        msg, query="q", results=results if results is not None else [{"sku": "A", "name": "X"}],
        constraints=c, brand_budget_answer="", trace_id=None, deterministic_fn=_det,
        guard_enabled_fn=lambda: enabled, verify_fn=lambda *a, **k: _GR(grounded),
    )
    return out, c.get("_claim_guard_status")


def test_disabled_reports_disabled_not_false_passed():
    out, status = _run(enabled=False, grounded=True)
    assert out == "LLM prose"           # unchanged
    assert status == "disabled"          # NOT a false "passed"


def test_enabled_grounded_reports_passed():
    out, status = _run(enabled=True, grounded=True)
    assert out == "LLM prose"
    assert status == "passed"


def test_enabled_ungrounded_rejected_and_falls_back():
    out, status = _run(enabled=True, grounded=False, msg="invented ThinkPad X1 Carbon at $999")
    assert out == "DETERMINISTIC FALLBACK"
    assert status == "fell_back_to_deterministic"


def test_enabled_but_nothing_to_check_is_skipped():
    out, status = _run(enabled=True, grounded=True, msg="", results=[])
    assert status == "skipped"


def test_guard_is_on_by_default():
    os.environ.pop("COMMERCE_NARRATION_GUARD", None)
    from src.app.services.product_claim_guard import guard_enabled
    assert guard_enabled() is True
    os.environ["COMMERCE_NARRATION_GUARD"] = "0"
    assert guard_enabled() is False
    os.environ.pop("COMMERCE_NARRATION_GUARD", None)
