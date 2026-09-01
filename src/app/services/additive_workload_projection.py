"""Fail-closed buyer projection for a newly added mandatory workload."""
from __future__ import annotations

from typing import Any


def catalog_authority_for_turn(
    semantic_authority: object,
    *,
    material_blocked: bool,
    has_products: bool,
    requirements_established: bool,
) -> str:
    """Resolve catalog authority without letting stale permissive state win."""
    if material_blocked:
        return "blocked"
    normalized = str(semantic_authority or "").strip().lower()
    if normalized in {"permitted", "blocked"}:
        return normalized
    if has_products and requirements_established:
        return "permitted"
    return "unknown"


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
