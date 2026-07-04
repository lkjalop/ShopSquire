"""Hybrid multi-intent decomposition — the deterministic fast-path plus the schema-constrained LLM binding
that catches the phrasings the regex misses, with the SAME grammar-rule validation on the model's output."""
import json

from src.app.services.intent_decomposer import decompose_turn


def _stub_llm(prompt: str) -> str:
    """A stub 'model' that returns the correct forced schema — keyed on the MESSAGE (after 'Message:'), not
    the prompt's rule examples."""
    msg = prompt.split("Message:")[-1]
    if "docking station" in msg:
        return json.dumps({"amendments": [{"ref": "__last__", "new_qty": 15}],
                           "new_lines": [{"category": "docking stations", "qty": 1}]})
    if "40 mice" in msg:
        return json.dumps({"amendments": [{"ref": "__last__", "new_qty": 10}],
                           "new_lines": [{"category": "mice", "qty": 40}]})
    return "{}"


def test_llm_binding_catches_new_line_the_regex_missed():
    # deterministic gets the amendment but not "add a docking station"
    det = decompose_turn("make it 15 and add a docking station", has_prior_selection=True)
    assert [(a.ref, a.new_qty) for a in det.amendments] == [("__last__", 15)]
    assert det.new_lines == []
    # hybrid adds the missed line via the LLM
    hyb = decompose_turn("make it 15 and add a docking station", has_prior_selection=True, llm_fn=_stub_llm)
    assert [(a.ref, a.new_qty) for a in hyb.amendments] == [("__last__", 15)]
    assert [(n.category, n.qty) for n in hyb.new_lines] == [("docking stations", 1)]


def test_llm_binding_recovers_a_fully_missed_turn():
    # deterministic gets NOTHING ("reduce" isn't in its verb set, "get 40 mice" lacks "me")
    det = decompose_turn("reduce to 10 and get 40 mice for the office", has_prior_selection=True)
    assert det.amendments == [] and det.new_lines == []
    hyb = decompose_turn("reduce to 10 and get 40 mice for the office", has_prior_selection=True, llm_fn=_stub_llm)
    assert [(a.ref, a.new_qty) for a in hyb.amendments] == [("__last__", 10)]
    assert [(n.category, n.qty) for n in hyb.new_lines] == [("mice", 40)]


def test_fast_path_skips_the_llm_when_deterministic_is_complete():
    # a turn the regex fully captures must NOT call the model — the llm_fn raises if invoked.
    def _boom(_p: str) -> str:
        raise AssertionError("LLM should not be called on a fully-captured turn")
    hyb = decompose_turn("actually 15 instead, what headsets and hard drives for 1200 for those",
                         has_prior_selection=True, llm_fn=_boom)
    assert [(a.ref, a.new_qty) for a in hyb.amendments] == [("__last__", 15)]
    assert sorted(n.category for n in hyb.new_lines) == ["hard drives", "headsets"]


def test_llm_output_is_validated_bad_qty_is_rejected():
    # the model returns an out-of-range qty + a stop-noun category → validation drops them → falls back
    def _bad(_p: str) -> str:
        return json.dumps({"amendments": [{"ref": "__last__", "new_qty": 99999}],
                           "new_lines": [{"category": "those", "qty": 3}]})
    hyb = decompose_turn("reduce to 10 and get 40 mice", has_prior_selection=True, llm_fn=_bad)
    # 99999 qty rejected (1..500) and 'those' is a stop-noun → nothing usable → deterministic stands (empty)
    assert hyb.amendments == [] and hyb.new_lines == []


def test_prior_context_makes_relative_language_computable():
    """'halve the order' is unanswerable without the prior qty — the binding prompt must carry it, and the
    model's computed absolute qty passes the same validator as any other number."""
    seen = {}

    def _halver(prompt: str) -> str:
        seen["prompt"] = prompt
        # the model can only answer because the prompt told it the prior quantity
        assert "quantity 20" in prompt
        return json.dumps({"amendments": [{"ref": "__last__", "new_qty": 10}]})

    hyb = decompose_turn("actually halve the laptop order", has_prior_selection=True,
                         llm_fn=_halver, prior_context={"qty": 20, "name": "Lenovo IdeaPad"})
    assert [(a.ref, a.new_qty) for a in hyb.amendments] == [("__last__", 10)]
    assert "item 'Lenovo IdeaPad'" in seen["prompt"]


def test_prior_context_absent_prompt_has_no_context_line():
    def _echo(prompt: str) -> str:
        assert "Prior selection:" not in prompt
        return "{}"
    decompose_turn("actually halve the laptop order", has_prior_selection=True, llm_fn=_echo)
