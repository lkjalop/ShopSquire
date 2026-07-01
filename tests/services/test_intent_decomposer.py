"""Multi-intent turn decomposition — the 'not-dumb' parser. Agnostic, deterministic, pure."""
from __future__ import annotations

from src.app.services import intent_decomposer as idc


SCENARIO = ("nah that's too expensive, actually i need 15 instead? what options for headsets and "
            "hard drives. i have a budget for 1200 for those?")


def test_full_scenario_decomposes_all_four_intents():
    t = idc.decompose_turn(SCENARIO, has_prior_selection=True)
    # 1) price objection
    assert t.objection == "price"
    # 2) quantity amendment on the LAST chosen item → 15 (not a new line, not 1500)
    assert len(t.amendments) == 1 and t.amendments[0].new_qty == 15 and t.amendments[0].ref == "__last__"
    # 3) two NEW category lines (headsets + hard drives), not "options"/"those"
    cats = {n.category for n in t.new_lines}
    assert "headsets" in cats and any("drive" in c for c in cats)
    assert "options" not in cats and "those" not in cats
    # 4) the $1200 is SCOPED to the new lines, NOT the laptop (no global budget)
    assert len(t.budget_scopes) == 1
    assert t.budget_scopes[0].budget_max == 1200 and t.budget_scopes[0].applies_to == ("__new__",)
    assert t.global_budget is None
    # a rich multi-intent turn → confidence lowered so the caller confirms
    assert t.confidence < 1.0


def test_amendment_ignored_without_prior_selection():
    t = idc.decompose_turn("actually make it 15 instead", has_prior_selection=False)
    assert t.amendments == [] and any("no prior selection" in n for n in t.notes)


def test_amendment_binds_with_prior_selection():
    assert idc.decompose_turn("make it 12 instead", has_prior_selection=True).amendments[0].new_qty == 12
    assert idc.decompose_turn("actually change to 8", has_prior_selection=True).amendments[0].new_qty == 8


def test_scoped_vs_global_budget():
    scoped = idc.decompose_turn("what headsets and cables for $1200 for those")
    assert scoped.budget_scopes and scoped.budget_scopes[0].budget_max == 1200 and scoped.global_budget is None
    glob = idc.decompose_turn("show me headsets, budget is 1200")   # no scope cue → global
    assert glob.global_budget == (None, 1200) and glob.budget_scopes == []


def test_new_lines_are_not_referents_or_units():
    t = idc.decompose_turn("what options for those, i need 20 units")
    cats = {n.category for n in t.new_lines}
    assert "those" not in cats and "units" not in cats and "options" not in cats


def test_quantified_new_line_is_not_an_amendment():
    # "add 10 monitors" — 10 is a NEW-LINE qty (followed by a category), NOT a qty amendment
    t = idc.decompose_turn("add 10 monitors", has_prior_selection=True)
    assert t.amendments == [] and any(n.category == "monitors" and n.qty == 10 for n in t.new_lines)


def test_budget_digits_are_not_read_as_quantity():
    t = idc.decompose_turn("actually i need 15 instead, budget 1200 for those", has_prior_selection=True)
    # 15 is the amendment; 1200 is the budget — never the reverse
    assert t.amendments and t.amendments[0].new_qty == 15
    assert (t.budget_scopes and t.budget_scopes[0].budget_max == 1200) or (t.global_budget == (None, 1200))


def test_plain_query_is_low_intent_and_safe():
    t = idc.decompose_turn("show me gaming laptops under 1500")
    assert t.objection is None and t.amendments == []
    assert t.global_budget == (None, 1500) and t.budget_scopes == []


def test_as_dict_shape():
    d = idc.decompose_turn(SCENARIO, has_prior_selection=True).as_dict()
    assert set(d) == {"amendments", "new_lines", "budget_scopes", "global_budget", "objection",
                      "confidence", "notes"}
