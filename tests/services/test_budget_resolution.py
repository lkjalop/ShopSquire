"""Property tests for the budget merge table (recommend_constraint_builder) — the four laws that were
violated by real demo bugs, plus provenance guarantees."""
from src.app.services.recommend_constraint_builder import (
    BudgetResolution, apply_budget_revisions, initial_budget)


# ── law 1: request param beats everything ─────────────────────────────────────────────────────────
def test_request_param_beats_everything():
    r = initial_budget(request_max=1800, parsed_max=1500, nlp_max=1400, decayed_max=1300, confirmed_max=1200)
    assert r.budget_max == 1800
    assert ("budget_max", "request", 1800) in r.provenance


# ── law 2: a fresh parse beats any memory ─────────────────────────────────────────────────────────
def test_fresh_parse_beats_decayed_pref():
    r = initial_budget(parsed_max=1000, decayed_max=1500, confirmed_max=1500)
    assert r.budget_max == 1000
    assert ("budget_max", "parsed", 1000) in r.provenance


def test_memory_fills_only_when_nothing_fresh():
    r = initial_budget(decayed_min=1200, decayed_max=1500)
    assert (r.budget_min, r.budget_max) == (1200, 1500)
    assert ("budget_min", "decayed", 1200) in r.provenance


# ── law 3: a cut clears the floor (one-sided reset) ───────────────────────────────────────────────
def test_cut_clears_stale_floor():
    r = apply_budget_revisions(
        current_min=1200, current_max=1000, parsed_min=None, parsed_max=1000,
        query_lower="cut it to 1000 max", asks_budget=True,
        explicit_constraint_update=True, references_prior=False, followup_explain=False)
    assert (r.budget_min, r.budget_max) == (None, 1000)
    assert ("budget_min", "one_sided_reset", None) in r.provenance


# ── law 4: a raise keeps the remembered floor (never on a cut verb) ──────────────────────────────
def test_raise_keeps_remembered_floor():
    r = apply_budget_revisions(
        current_min=None, current_max=1800, parsed_min=None, parsed_max=1800,
        query_lower="actually budget is now 1800 max", asks_budget=True,
        explicit_constraint_update=True, references_prior=False, followup_explain=False,
        decayed_min=1200)
    assert (r.budget_min, r.budget_max) == (1200, 1800)
    assert ("budget_min", "floor_carry", 1200) in r.provenance


def test_cut_verb_never_carries_the_floor():
    r = apply_budget_revisions(
        current_min=None, current_max=1000, parsed_min=None, parsed_max=1000,
        query_lower="actually cut it to 1000 max", asks_budget=True,
        explicit_constraint_update=True, references_prior=False, followup_explain=False,
        decayed_min=1200)
    assert r.budget_min is None


# ── supporting rules ──────────────────────────────────────────────────────────────────────────────
def test_inverted_band_swaps_without_a_cue():
    r = apply_budget_revisions(
        current_min=1500, current_max=1200, parsed_min=None, parsed_max=None,
        query_lower="budget stuff", asks_budget=True,
        explicit_constraint_update=False, references_prior=False, followup_explain=False)
    assert (r.budget_min, r.budget_max) == (1200, 1500)


def test_spec_only_turn_clears_the_envelope():
    r = apply_budget_revisions(
        current_min=1200, current_max=1500, parsed_min=None, parsed_max=None,
        query_lower="16gb ram with an oled screen", asks_budget=False,
        explicit_constraint_update=True, references_prior=False, followup_explain=False)
    assert (r.budget_min, r.budget_max) == (None, None)
    assert ("budget_max", "spec_turn_clear", None) in r.provenance


def test_deictic_followup_reloads_memory():
    r = apply_budget_revisions(
        current_min=None, current_max=None, parsed_min=None, parsed_max=None,
        query_lower="tell me more about those", asks_budget=False,
        explicit_constraint_update=False, references_prior=True, followup_explain=True,
        nlp_min=1200, nlp_max=1500)
    assert (r.budget_min, r.budget_max) == (1200, 1500)
    assert ("budget_max", "memory_reload", 1500) in r.provenance


def test_pure_and_deterministic():
    kw = dict(current_min=1200, current_max=1000, parsed_min=None, parsed_max=1000,
              query_lower="cut it to 1000 max", asks_budget=True,
              explicit_constraint_update=True, references_prior=False, followup_explain=False)
    a, b = apply_budget_revisions(**kw), apply_budget_revisions(**kw)
    assert a == b and isinstance(a, BudgetResolution)
