"""The agnostic 'when to leverage market intel' gate (query_decomposer.needs_market_evidence).

Keyed on INTENT shape, not vertical vocabulary — so it fires the same on laptops, shoes, or drugs.
A plain product lookup / support question must NOT fire (the swarm shouldn't pay the cost).
"""
from __future__ import annotations

import pytest

from src.app.services.query_decomposer import decompose


@pytest.mark.parametrize("q,kind", [
    ("what laptops are trending right now", "demand"),
    ("show me the most popular headphones", "demand"),
    ("best selling monitors", "demand"),
    ("dell xps vs macbook air", "competitor"),
    ("is this cheaper elsewhere", "competitor"),
    ("is the framework 16 worth it", "historical_outcome"),
    ("should i wait to buy a new phone", "historical_outcome"),
])
def test_market_evidence_fires_on_intent(q, kind):
    plan = decompose(q)
    assert plan.needs_market_evidence is True
    assert kind in plan.market_evidence_kinds


def test_bulk_implies_supply_evidence():
    plan = decompose("I need 10 laptops for the company")
    assert plan.needs_market_evidence is True
    assert "supply" in plan.market_evidence_kinds


@pytest.mark.parametrize("q", [
    "a laptop for university under 1500",
    "show me a dell xps 13",
    "where is my order",
    "gaming laptop with rtx 4070",
])
def test_plain_queries_do_not_fire(q):
    plan = decompose(q)
    assert plan.needs_market_evidence is False
    assert plan.market_evidence_kinds == []


def test_agnostic_same_signal_across_verticals():
    # the SAME intent word fires regardless of product domain (no vertical vocabulary)
    assert decompose("trending shoes").needs_market_evidence is True
    assert decompose("trending laptops").needs_market_evidence is True
    assert decompose("trending vitamins").needs_market_evidence is True


def test_serialized_in_to_dict():
    d = decompose("what is trending").to_dict()
    assert d["needs_market_evidence"] is True
    assert "demand" in d["market_evidence_kinds"]
