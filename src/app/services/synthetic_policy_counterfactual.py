"""Bounded, simulation-only inventory-policy counterfactuals.

These comparisons replay the same synthetic latent demand and lead-time
sequence under two reorder policies. They are useful for discrimination in the
lab, but are not causal evidence and can never authorize execution.
"""
from __future__ import annotations

import statistics
from typing import Any


def _undefined(status: str, detail: str) -> dict[str, Any]:
    return {
        "status": status,
        "detail": detail,
        "authority": "simulation_only",
        "execution_allowed": False,
        "causal_claim_allowed": False,
        "baseline": None,
        "candidate": None,
        "delta": None,
    }


def _simulate_policy(
    *,
    demand: list[int],
    initial_inventory: int,
    reorder_point: float,
    reorder_quantity: int,
    lead_times: list[int],
    unit_cost_minor: int,
    shock_day: int,
    shock_unit_cost_minor: int,
) -> dict[str, Any]:
    on_hand = max(0, int(initial_inventory))
    arrivals: dict[int, int] = {}
    closing: list[int] = []
    lost_units = 0
    stockout_days = 0
    purchase_orders = 0
    purchased_units = 0
    purchase_spend = 0
    for day, requested in enumerate(demand):
        on_hand += arrivals.pop(day, 0)
        sold = min(on_hand, max(0, int(requested)))
        lost = max(0, int(requested) - sold)
        on_hand -= sold
        lost_units += lost
        stockout_days += int(lost > 0)
        incoming = sum(
            quantity
            for receipt_day, quantity in arrivals.items()
            if receipt_day > day
        )
        if on_hand + incoming <= reorder_point:
            lead_time = lead_times[purchase_orders % len(lead_times)]
            receipt_day = day + lead_time
            arrivals[receipt_day] = arrivals.get(receipt_day, 0) + reorder_quantity
            cost = shock_unit_cost_minor if day >= shock_day else unit_cost_minor
            purchase_orders += 1
            purchased_units += reorder_quantity
            purchase_spend += reorder_quantity * cost
        closing.append(on_hand)
    total_demand = sum(demand)
    filled = total_demand - lost_units
    return {
        "policy": {
            "reorder_point_units": round(float(reorder_point), 4),
            "reorder_quantity_units": int(reorder_quantity),
        },
        "fill_rate": round(filled / total_demand, 6),
        "lost_units": lost_units,
        "stockout_days": stockout_days,
        "average_on_hand_units": round(statistics.fmean(closing), 6),
        "purchase_orders": purchase_orders,
        "purchased_units": purchased_units,
        "purchase_spend_minor": purchase_spend,
    }


def compare_inventory_policies(
    replay: dict[str, Any],
    *,
    candidate_reorder_point: float | None,
    candidate_reorder_quantity: int | None,
    candidate_label: str,
) -> dict[str, Any]:
    history = list((replay.get("history") or {}).get("daily_history") or [])
    profile = dict(replay.get("profile") or {})
    purchase_orders = list((replay.get("history") or {}).get("purchase_orders") or [])
    if not history:
        return _undefined("undefined_no_history", "synthetic daily history is required")
    demand = [max(0, int(row.get("latent_demand_units") or 0)) for row in history]
    if sum(demand) <= 0:
        return _undefined(
            "undefined_zero_demand",
            "bounded utility is undefined when aggregate latent demand is zero",
        )
    if candidate_reorder_point is None or candidate_reorder_quantity is None:
        return _undefined(
            "undefined_candidate_policy",
            "candidate reorder point and quantity were not supported by forecast evidence",
        )
    baseline_point = float(profile.get("reorder_point") or 0)
    baseline_quantity = int(profile.get("reorder_quantity") or 0)
    candidate_quantity = int(candidate_reorder_quantity)
    if baseline_point < 0 or baseline_quantity <= 0 or candidate_reorder_point < 0 or candidate_quantity <= 0:
        return _undefined(
            "undefined_invalid_policy",
            "both policies require a non-negative reorder point and positive quantity",
        )
    lead_times = [
        max(1, int(row.get("planned_lead_time_days") or 0))
        for row in purchase_orders
        if int(row.get("planned_lead_time_days") or 0) > 0
    ]
    if not lead_times:
        fallback = int(profile.get("lead_time_mean_days") or 0)
        if fallback <= 0:
            return _undefined(
                "undefined_lead_time",
                "no lead-time evidence was available for replay",
            )
        lead_times = [fallback]
    unit_cost = int(profile.get("unit_cost_minor") or 0)
    shock_cost = int(round(
        unit_cost
        * (1.0 + float(profile.get("shock_cost_pass_through_pct") or 0.0) / 100.0)
    ))
    common = {
        "demand": demand,
        "initial_inventory": int(profile.get("initial_inventory") or 0),
        "lead_times": lead_times,
        "unit_cost_minor": unit_cost,
        "shock_day": int(profile.get("shock_day") or len(history)),
        "shock_unit_cost_minor": shock_cost,
    }
    baseline = _simulate_policy(
        **common,
        reorder_point=baseline_point,
        reorder_quantity=baseline_quantity,
    )
    candidate = _simulate_policy(
        **common,
        reorder_point=float(candidate_reorder_point),
        reorder_quantity=candidate_quantity,
    )

    # A transparent, bounded [0, 1] utility for synthetic comparison only.
    # Service dominates; the inventory term is capped at four mean lead-time
    # demand cycles so extreme stock cannot create unbounded scores.
    mean_daily = statistics.fmean(demand)
    inventory_cap = max(
        1.0,
        mean_daily * max(lead_times) * 4.0,
    )
    for row in (baseline, candidate):
        inventory_efficiency = 1.0 - min(
            1.0,
            float(row["average_on_hand_units"]) / inventory_cap,
        )
        row["bounded_utility"] = round(
            0.8 * float(row["fill_rate"]) + 0.2 * inventory_efficiency,
            6,
        )
        row["inventory_efficiency"] = round(inventory_efficiency, 6)
    return {
        "status": "observed",
        "authority": "simulation_only",
        "execution_allowed": False,
        "causal_claim_allowed": False,
        "candidate_label": str(candidate_label),
        "baseline": baseline,
        "candidate": candidate,
        "delta": {
            key: round(float(candidate[key]) - float(baseline[key]), 6)
            for key in (
                "fill_rate",
                "lost_units",
                "stockout_days",
                "average_on_hand_units",
                "purchase_spend_minor",
                "bounded_utility",
            )
        },
        "utility_definition": {
            "range": [0.0, 1.0],
            "weights": {"fill_rate": 0.8, "inventory_efficiency": 0.2},
            "inventory_penalty_cap": "four_mean_lead_time_demand_cycles",
            "limitations": [
                "synthetic latent demand and replayed lead-time sequence only",
                "not a causal estimate",
                "does not price lost goodwill, expiry, storage, financing, or capacity",
                "cannot increase autonomy",
            ],
        },
    }

