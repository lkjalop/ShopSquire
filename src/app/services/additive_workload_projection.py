"""Fail-closed buyer projection for a newly added mandatory workload."""
from __future__ import annotations

from typing import Any


def hold_prior_slate(
    receipt: dict[str, Any],
    slots: dict[str, Any] | None,
) -> tuple[list, str]:
    budget = slots.get("budget_max") if isinstance(slots, dict) else None
    added = str(receipt.get("added_buyer_turn") or "the newly required workload").strip()
    budget_text = (
        f" I retained your AUD {int(budget):,} budget."
        if isinstance(budget, (int, float))
        else ""
    )
    return [], (
        f"I kept the existing workload and added {added} to the same case.{budget_text} "
        "I cannot qualify the earlier products against the combined objective until the added "
        "workload's current requirements are established. No cart or supplier action was authorized."
    )
