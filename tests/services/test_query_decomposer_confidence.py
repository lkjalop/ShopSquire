"""NEW-5 — decomposition_confidence on QueryPlan (agnostic core).

A deterministic 0..1 score of how many structured signals the rules extracted. A fully-specified
query scores high; an unparseable novel phrasing scores low (eligible for the LLM-planner fallback).
"""
from __future__ import annotations

from src.app.services.query_decomposer import decompose


def test_fully_specified_query_scores_high():
    plan = decompose("gaming laptop under $1500")
    assert plan.decomposition_confidence >= 0.6
    assert "decomposition_confidence" in plan.to_dict()


def test_unparseable_query_scores_low():
    plan = decompose("the thing for doing my stuff that everyone keeps raving about lately")
    assert plan.decomposition_confidence <= 0.2


def test_empty_query_is_zero():
    assert decompose("").decomposition_confidence == 0.0


def test_confidence_is_bounded_0_1():
    # Pile on every signal — score must clamp at 1.0, never exceed it.
    plan = decompose("10 gaming and video editing laptops between $1500 and $2500 with 32gb but not Apple, can you deliver in 2 weeks?")
    assert 0.0 <= plan.decomposition_confidence <= 1.0


def test_more_signals_scores_higher():
    bare = decompose("a laptop")
    rich = decompose("gaming laptop under $1500 with 32gb")
    assert rich.decomposition_confidence > bare.decomposition_confidence
