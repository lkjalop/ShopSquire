"""Leakage-safe price baselines over append-only shopping-case observations."""
from __future__ import annotations

from typing import Any


def _ewma(values: list[int], alpha: float) -> float:
    estimate = float(values[0])
    for value in values[1:]:
        estimate = alpha * float(value) + (1.0 - alpha) * estimate
    return estimate


def project_price_baselines(
    observations: list[dict[str, Any]], *, alpha: float = 0.3, season_length: int = 7,
) -> dict[str, Any]:
    """Compare causal one-step baselines; each prediction sees only prior values."""

    rows = sorted(
        (row for row in observations if row.get("kind") == "price"),
        key=lambda row: (str(row.get("known_at") or ""), str(row.get("observation_id") or "")),
    )
    values = [int((row.get("value") or {})["amount_cents"]) for row in rows]
    currencies = {str((row.get("value") or {}).get("currency") or "").upper() for row in rows}
    if len(currencies) > 1:
        return {"status": "not_comparable", "reason": "mixed_currency_without_fx_authority"}
    if len(values) < 3:
        return {
            "status": "insufficient_history", "observation_count": len(values),
            "minimum_required": 3, "authority": "descriptive_baseline_only",
        }
    errors = {"seasonal_naive": [], "ewma": []}
    evaluation_pairs: list[dict[str, Any]] = []
    for index in range(1, len(values)):
        history = values[:index]
        seasonal = history[-season_length] if len(history) >= season_length else history[-1]
        ewma_prediction = _ewma(history, alpha)
        errors["seasonal_naive"].append(abs(float(values[index] - seasonal)))
        errors["ewma"].append(abs(float(values[index]) - ewma_prediction))
        evaluation_pairs.append({
            "target_observation_id": rows[index].get("observation_id"),
            "target_known_at": rows[index].get("known_at"),
            "actual_minor_units": values[index],
            "predictions_minor_units": {
                "seasonal_naive": seasonal,
                "ewma": round(ewma_prediction, 2),
            },
            "training_observation_count": len(history),
        })
    mae = {name: round(sum(rows_) / len(rows_), 4) for name, rows_ in errors.items()}
    winner = min(mae, key=lambda name: (mae[name], name))
    return {
        "status": "measured", "observation_count": len(values),
        "currency": next(iter(currencies)), "alpha": alpha,
        "season_length": season_length, "mae_minor_units": mae,
        "selected_baseline": winner,
        "next_price_minor_units": {
            "seasonal_naive": values[-season_length] if len(values) >= season_length else values[-1],
            "ewma": round(_ewma(values, alpha), 2),
        },
        "evaluation_pairs": evaluation_pairs,
        "evaluation_semantics": "prequential_each_actual_scored_from_prior_observations_only",
        "authority": "descriptive_baseline_only",
        "pricing_authority_granted": False,
    }


__all__ = ["project_price_baselines"]
