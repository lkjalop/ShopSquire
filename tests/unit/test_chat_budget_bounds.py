"""chat._extract_budget_bounds — natural budget phrasings parse correctly, and quantities/specs never
read as a price. Regression for the trust bug where 'budget about 1900 each' parsed to None → no band →
$4,500 units surfaced for a $1,900 query."""
from __future__ import annotations

import pytest

from src.app.routers.chat import _extract_budget_bounds as b


@pytest.mark.parametrize("query,bmin,bmax", [
    ("i need 15 laptops, budget is about 1900 each?", None, 1900),
    ("15 laptops budget 1900 each", None, 1900),
    ("work laptop from 1300 to 1500", 1300, 1500),
    ("$1300-$1800", 1300, 1800),
    ("laptops under 1500", None, 1500),
    ("between 1300 and 1800", 1300, 1800),
    ("over 2000", 2000, None),
    ("at least 2500", 2500, None),
    ("i can spend about $2000", None, 2000),
    ("around $1800 per laptop", None, 1800),
    ("no more than 1200", None, 1200),
])
def test_budget_phrasings_parse(query, bmin, bmax):
    got = b(query)
    assert got["budget_max"] == bmax, f"{query!r} -> {got}"
    if bmin is not None:
        assert got["budget_min"] == bmin, f"{query!r} -> {got}"


@pytest.mark.parametrize("query", [
    "show me 15 gaming laptops",          # quantity is not a budget
    "rtx 4070 144hz 16gb laptop",         # specs are not a budget
    "2560 x 1600 oled display",           # resolution is not a budget
    "i need a laptop for university",     # no amount
])
def test_non_budget_text_returns_none(query):
    got = b(query)
    assert got["budget_min"] is None and got["budget_max"] is None, f"{query!r} -> {got}"
