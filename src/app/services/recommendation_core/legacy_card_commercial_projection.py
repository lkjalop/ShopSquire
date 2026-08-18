"""Bridge covered-persona cards onto the canonical commercial reducer."""
from __future__ import annotations

from typing import Any

from src.app.services.commercial_decision_reducer import (
    CommercialCandidate,
    reduce_commercial_candidate,
)


def project_legacy_card_commercial_decision(
    card: Any,
    *,
    budget_per_unit_cents: int | None,
    requested_quantity: int,
    deadline_days: int | None,
) -> dict[str, Any]:
    """Classify an old ProductCard without inventing exact-config evidence."""

    fit = card.fit if isinstance(getattr(card, "fit", None), dict) else {}
    overall = str(fit.get("overall") or "").lower()
    exact_identity = bool(fit.get("exact_identity") is True)
    freshness = str(fit.get("specification_freshness") or "unknown").lower()
    if freshness not in {"fresh", "stale", "unknown"}:
        freshness = "unknown"
    misses = []
    if overall == "fails":
        per_key = fit.get("per_key") if isinstance(fit.get("per_key"), dict) else {}
        misses = [
            str(key) for key, verdict in per_key.items()
            if str(verdict).lower() in {"fails", "below_minimum", "miss"}
        ] or ["workload requirements"]
    unknowns = []
    if overall not in {"meets", "fails"}:
        unknowns.append("workload fit")
    if not exact_identity:
        unknowns.append("exact configuration identity")
    decision = reduce_commercial_candidate(CommercialCandidate(
        sku=str(card.sku), exact_identity=exact_identity,
        verified_minimum_misses=misses,
        material_unknowns=unknowns,
        specification_freshness=freshness,
        unit_price_cents=card.price_cents,
        currency=str(card.currency or "AUD"),
        budget_per_unit_cents=budget_per_unit_cents,
        requested_quantity=max(1, int(requested_quantity or 1)),
        local_available_now=(
            max(0, int(card.stock)) if card.stock is not None else None
        ),
        deadline_days=deadline_days,
    ))
    projection = decision.model_dump(mode="json")
    projection["projection_source"] = "canonical_commercial_reducer"
    projection["ranking_authority_granted"] = False
    return projection


__all__ = ["project_legacy_card_commercial_decision"]
