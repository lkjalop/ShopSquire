from __future__ import annotations

from src.app.eval.runner import load_cases, run_intent_slot_eval


def test_intent_slot_eval_baseline():
    cases = load_cases("tests/evals/intent_slots.jsonl")
    metrics = run_intent_slot_eval(cases)
    assert metrics["intent_accuracy"] >= 0.6
    assert metrics["slot_accuracy"] >= 0.5
