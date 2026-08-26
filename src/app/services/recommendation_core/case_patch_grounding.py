"""Deterministic buyer-utterance grounding for canonical case-patch completion."""

from __future__ import annotations

from src.app.services.budget_grammar import parse_budget
from src.app.services.bulk_intent import quantity_value_mentioned


def quantity_is_current(query: str, requested_quantity: int | None) -> bool:
    """Return true only when this turn independently mentions the quantity."""

    return bool(
        requested_quantity is not None
        and quantity_value_mentioned(query, requested_quantity)
    )


def budget_is_current(query: str, total_budget_cents: int | None) -> bool:
    """Return true only when this turn independently mentions the parsed budget."""

    parsed = parse_budget(query)
    return bool(
        total_budget_cents is not None
        and parsed is not None
        and total_budget_cents in {
            int(amount) * 100
            for amount in (parsed.budget_min, parsed.budget_max)
            if amount is not None
        }
    )


__all__ = ["budget_is_current", "quantity_is_current"]
