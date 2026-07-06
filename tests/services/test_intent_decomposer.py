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


def test_plain_bulk_search_does_not_surface_new_lines():
    # "what laptops for work? ... I need about 25" trips a request cue but is SINGLE-intent (no prior, no
    # amendment, no scope cue, no add verb) — it must NOT emit a new-line (the bulk-query false multi-intent
    # card GPT-5.5 flagged). Budget still parses.
    t = idc.decompose_turn("what laptops for work? budget 1500 to 1900, I need about 25", has_prior_selection=False)
    assert t.new_lines == [] and t.amendments == []
    assert t.global_budget == (1500, 1900)


def test_new_lines_survive_with_an_add_cue_or_prior_or_scope():
    # explicit add verb, no prior → the buyer really is asking to add categories
    a = idc.decompose_turn("get me 5 headsets and 10 hard drives", has_prior_selection=False)
    assert {n.category for n in a.new_lines} == {"headsets", "hard drives"}
    # amendment + add + scope, with a prior selection → the full mixed turn is preserved
    b = idc.decompose_turn("actually make it 15 and get me 5 headsets and 10 hard drives for 2000 for those",
                           has_prior_selection=True)
    assert b.amendments and b.amendments[0].new_qty == 15
    assert {n.category for n in b.new_lines} == {"headsets", "hard drives"}


# ── cart-operation grammar: removals + named refs + multi-amendment (the live compound command) ──
def test_compound_removals_and_named_qty_all_parse():
    """The live regression verbatim: two removals + a named qty change in ONE turn. Previously this fell
    through to product search (no removal grammar, one __last__ amendment max)."""
    from src.app.services.intent_decomposer import decompose_turn
    q = ('can we get rid off the HP Envy x360 14-fc0189TU 14" WUXGA and Lenovo ThinkPad L13 Gen 6 13.3" '
         'WUXGA reduce Lenovo IdeaPad Slim 3i 15.3" 2K Laptop to 20 instead? do i have to redo delivery plan?')
    t = decompose_turn(q, has_prior_selection=True)
    ops = [(a.ref.lower(), a.new_qty) for a in t.amendments]
    assert len(ops) == 3, ops
    assert any("envy" in r and n == 0 for r, n in ops), "HP Envy removal missing"
    assert any("thinkpad" in r and n == 0 for r, n in ops), "ThinkPad removal missing"
    assert any("ideapad" in r and n == 20 for r, n in ops), "IdeaPad qty-20 missing"


def test_removal_needs_a_prior_selection():
    from src.app.services.intent_decomposer import decompose_turn
    t = decompose_turn("remove the monitor", has_prior_selection=False)
    assert not t.amendments and any("no prior selection" in n for n in t.notes)


def test_bare_last_amendment_still_single_and_unclaimed_numbers_only():
    """'make it 15' keeps the positional __last__ path; numbers inside removal/named spans are never
    double-counted as bare amendments."""
    from src.app.services.intent_decomposer import decompose_turn
    t = decompose_turn("actually make it 15 instead", has_prior_selection=True)
    assert [(a.ref, a.new_qty) for a in t.amendments] == [("__last__", 15)]
    t2 = decompose_turn("reduce the ideapad slim to 20", has_prior_selection=True)
    assert len(t2.amendments) == 1 and t2.amendments[0].new_qty == 20
    assert t2.amendments[0].ref != "__last__"
