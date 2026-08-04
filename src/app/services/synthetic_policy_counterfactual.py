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
    sale_price_minor: int,
    shock_day: int,
    shock_unit_cost_minor: int,
    shelf_life_days: int | None,
) -> dict[str, Any]:
    initial = max(0, int(initial_inventory))
    on_hand = initial
    arrivals: dict[int, int] = {}
    # Lots are intentionally internal to this simulation. Canonical facts are
    # never rewritten; the same receipt sequence is replayed under each policy.
    lots: list[dict[str, int | None]] = [{
        "quantity": initial,
        "expires_day": (
            max(1, int(shelf_life_days))
            if shelf_life_days is not None
            else None
        ),
        "unit_cost_minor": int(unit_cost_minor),
    }]
    closing: list[int] = []
    lost_units = 0
    waste_units = 0
    waste_value_minor = 0
    stockout_days = 0
    purchase_orders = 0
    purchased_units = 0
    purchase_spend = 0
    for day, requested in enumerate(demand):
        arrived = arrivals.pop(day, 0)
        if arrived:
            receipt_cost = (
                shock_unit_cost_minor if day >= shock_day else unit_cost_minor
            )
            lots.append({
                "quantity": arrived,
                "expires_day": (
                    day + max(1, int(shelf_life_days))
                    if shelf_life_days is not None
                    else None
                ),
                "unit_cost_minor": receipt_cost,
            })
            on_hand += arrived
        for lot in lots:
            expires_day = lot["expires_day"]
            quantity = int(lot["quantity"] or 0)
            if quantity and expires_day is not None and int(expires_day) <= day:
                waste_units += quantity
                waste_value_minor += quantity * int(lot["unit_cost_minor"] or 0)
                on_hand -= quantity
                lot["quantity"] = 0
        requested_units = max(0, int(requested))
        sold = min(on_hand, requested_units)
        lost = max(0, int(requested) - sold)
        remaining_sale = sold
        # FEFO is deterministic and prevents newer stock being consumed while
        # an earlier-expiring lot remains.
        lots.sort(key=lambda lot: (
            lot["expires_day"] is None,
            int(lot["expires_day"] or 0),
        ))
        for lot in lots:
            if remaining_sale <= 0:
                break
            consumed = min(int(lot["quantity"] or 0), remaining_sale)
            lot["quantity"] = int(lot["quantity"] or 0) - consumed
            remaining_sale -= consumed
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
        "filled_units": filled,
        "lost_units": lost_units,
        "stockout_days": stockout_days,
        "average_on_hand_units": round(statistics.fmean(closing), 6),
        "gross_margin_minor": filled * max(0, sale_price_minor - unit_cost_minor),
        "working_capital_minor": round(
            statistics.fmean(closing) * unit_cost_minor,
        ),
        "service_impact": round(
            (filled / total_demand) - (stockout_days / len(demand)),
            6,
        ),
        "purchase_orders": purchase_orders,
        "purchased_units": purchased_units,
        "purchase_spend_minor": purchase_spend,
        "waste_units": waste_units,
        "waste_value_minor": waste_value_minor,
        "ageing_status": (
            "observed_fefo_expiry"
            if shelf_life_days is not None
            else "observed_non_expiring"
        ),
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
    sale_price = int(
        profile.get("current_price_minor") or round(unit_cost * 1.5)
    )
    shock_cost = int(round(
        unit_cost
        * (1.0 + float(profile.get("shock_cost_pass_through_pct") or 0.0) / 100.0)
    ))
    common = {
        "demand": demand,
        "initial_inventory": int(profile.get("initial_inventory") or 0),
        "lead_times": lead_times,
        "unit_cost_minor": unit_cost,
        "sale_price_minor": sale_price,
        "shock_day": int(profile.get("shock_day") or len(history)),
        "shock_unit_cost_minor": shock_cost,
        "shelf_life_days": (
            max(1, int(profile["shelf_life_days"]))
            if profile.get("shelf_life_days") is not None
            else None
        ),
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
                "gross_margin_minor",
                "working_capital_minor",
                "service_impact",
                "bounded_utility",
                "waste_units",
                "waste_value_minor",
            )
        },
        "utility_definition": {
            "range": [0.0, 1.0],
            "weights": {"fill_rate": 0.8, "inventory_efficiency": 0.2},
            "inventory_penalty_cap": "four_mean_lead_time_demand_cycles",
            "limitations": [
                "synthetic latent demand and replayed lead-time sequence only",
                "not a causal estimate",
                "margin uses the declared current price and base unit cost",
                "working capital uses average units at base unit cost",
                "expiry waste uses deterministic FEFO lots and declared shelf life",
                "does not price lost goodwill, storage, financing, or capacity",
                "cannot increase autonomy",
            ],
        },
    }
