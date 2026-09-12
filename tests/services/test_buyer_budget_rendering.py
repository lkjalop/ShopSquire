"""Rendering contracts independent of query parsing and model output."""
from types import SimpleNamespace

import pytest

from src.app.services.answer_quality import _render_budget_decision
from src.app.services.recommendation_core.core import _bulk_message


@pytest.mark.parametrize("labels", [[], ["general"], ["General"], [" general "]])
@pytest.mark.parametrize("verdict", ["fits", "unsized", "over_budget"])
def test_generic_bulk_labels_are_buyer_prose(labels, verdict):
    message = _bulk_message({
        "quantity": 2000, "qualified_unit_floor_cents": 62900,
        "required_total_cents": 125800000, "total_budget_cents": 400000000,
        "verdict": verdict, "tradeoffs": [],
    }, SimpleNamespace(use_cases=labels))
    assert "for your use case" in message
    assert "for general" not in message.lower()


@pytest.mark.parametrize("budget,price,band", [
    (2000, 629, "$629-$2,000"),
    (2000.0, 629.0, "$629-$2,000"),
    (2000.50, 629.95, "$629.95-$2,000.50"),
])
def test_budget_band_has_normalized_currency_without_losing_cents(budget, price, band):
    message = _render_budget_decision(
        query="", products=[{"price": price}], base_message="Base.",
        canonical_budget={"budget_max": budget},
    )
    assert f"{band}. Base." in message


def test_total_budget_unit_cap_preserves_cents():
    message = _render_budget_decision(
        query="", products=[{"price": 629.95}], base_message="Base.",
        canonical_budget={"budget_max": 4001},
        bulk_budget={"budget_scope": "total", "per_unit_cap_cents": 200050},
    )
    assert "$629.95-$2,000.50." in message
