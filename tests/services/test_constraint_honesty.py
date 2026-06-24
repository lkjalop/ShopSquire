"""Constraint honesty (GPT-5.5 #2) — the hard filter must never silently present constraint-violating
products as a clean match. When a hard constraint eliminates every candidate, it returns the closest
set but flags exact_match=False, names the violated constraints, and offers relaxation.
"""
from __future__ import annotations

from src.app.routers.recommend import _apply_query_plan_filters, _constraint_relaxation_note


class _Plan:
    def __init__(self, hc, category="laptop", intent="product_search"):
        self.hard_constraints = hc
        self.category = category
        self.intent = intent


def _cands():
    return [
        {"name": "Laptop A", "sku": "A", "specs": {"refresh_hz": 60, "ram_gb": 16}},
        {"name": "Laptop B", "sku": "B", "specs": {"refresh_hz": 75, "ram_gb": 8}},
    ]


def test_unsatisfiable_constraint_reports_no_exact_match_not_silent():
    # Require 240Hz; both candidates are 60/75Hz → all eliminated → honest revert.
    results, dropped = _apply_query_plan_filters(_cands(), _Plan({"refresh_hz_min": 240}))
    assert results, "must still return the closest set, never blank"
    assert dropped.get("exact_match") is False
    assert "refresh" in (dropped.get("violated_constraints") or [])
    assert dropped.get("reverted") is True


def test_satisfiable_constraint_is_exact_match():
    results, dropped = _apply_query_plan_filters(_cands(), _Plan({"refresh_hz_min": 60}))
    assert len(results) == 2
    assert dropped.get("exact_match") is True
    assert "violated_constraints" not in dropped


def test_partial_filter_keeps_survivors_as_exact():
    # ram_gb_min=16 drops B (8GB), keeps A (16GB) → exact match on the survivor.
    results, dropped = _apply_query_plan_filters(_cands(), _Plan({"ram_gb_min": 16}))
    assert [r["sku"] for r in results] == ["A"]
    assert dropped.get("exact_match") is True
    assert dropped.get("ram") == 1


def test_relaxation_note_names_constraints_and_offers_relaxation():
    note = _constraint_relaxation_note(["refresh", "weight"])
    assert "no exact match" in note.lower()
    assert "refresh-rate" in note and "weight/portability" in note
    assert "relax" in note.lower()


def test_relaxation_note_generic_fallback():
    note = _constraint_relaxation_note([])
    assert "no exact match" in note.lower() and "relax" in note.lower()
