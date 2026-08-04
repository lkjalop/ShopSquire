"""Deterministic, configuration-driven supply scenarios.

Scenario vocabulary belongs to data under ``config/``. The generator has no
product-category branches and every emitted record is permanently simulated.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SCENARIO_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "synthetic_supply_scenarios.json"
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def generate_supply_scenario(
    scenario_id: str,
    *,
    seed: int,
    path: str | Path | None = None,
) -> dict[str, Any]:
    selected = Path(path).resolve() if path else SCENARIO_PATH
    payload = json.loads(selected.read_text(encoding="utf-8"))
    scenario = copy.deepcopy((payload.get("scenarios") or {}).get(str(scenario_id)))
    if not isinstance(scenario, dict):
        raise ValueError("synthetic_supply_scenario_not_found")
    generator_version = str(payload.get("generator_version") or "")
    if not generator_version:
        raise ValueError("synthetic_supply_generator_version_required")
    parameters = {
        "scenario_id": str(scenario_id),
        "seed": int(seed),
        "generator_version": generator_version,
        "scenario": scenario,
    }
    parameter_hash = hashlib.sha256(_canonical(parameters).encode("utf-8")).hexdigest()
    provenance = [
        f"synthetic_supply/{generator_version}",
        f"scenario/{scenario_id}",
        f"parameter_hash/{parameter_hash}",
    ]
    nodes = []
    for raw in scenario.get("nodes") or []:
        row = dict(raw)
        row.update({
            "tenant_id": "synthetic-lab",
            "evidence_status": "simulated",
            "simulation_only": True,
            "provenance_chain": provenance,
        })
        nodes.append(row)
    edges = []
    for raw in scenario.get("edges") or []:
        row = dict(raw)
        row.update({
            "tenant_id": "synthetic-lab",
            "evidence_status": "simulated",
            "simulation_only": True,
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": None,
            "provenance_chain": provenance,
        })
        edges.append(row)
    signals = []
    for raw in scenario.get("signals") or []:
        row = dict(raw)
        row.update({
            "tenant_id": "synthetic-lab",
            "status": "simulated",
            "simulation_only": True,
            "source_record_id": row.get("id"),
            "provenance_chain": provenance + [str(row.get("id"))],
        })
        signals.append(row)
    return {
        "manifest": {
            "scenario_id": str(scenario_id),
            "description": str(scenario.get("description") or ""),
            "seed": int(seed),
            "generator_version": generator_version,
            "parameter_hash": parameter_hash,
            "authority": "simulation_only",
            "replayable": True,
        },
        "nodes": nodes,
        "edges": edges,
        "signals": signals,
    }


def generate_commerce_history(
    scenario_id: str,
    *,
    seed: int,
    days: int = 400,
    start_date: date = date(2025, 1, 1),
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a deterministic inventory history from generic scenario dimensions.

    The model intentionally separates latent demand from observed sales. Product
    behaviour comes only from the versioned scenario profile, never category
    branches. These histories are evaluation fixtures, not authoritative facts.
    """
    if days < 1:
        raise ValueError("synthetic_history_days_must_be_positive")
    scenario = generate_supply_scenario(scenario_id, seed=seed, path=path)
    selected = Path(path).resolve() if path else SCENARIO_PATH
    payload = json.loads(selected.read_text(encoding="utf-8"))
    raw_scenario = (payload.get("scenarios") or {}).get(str(scenario_id)) or {}
    profile = dict(raw_scenario.get("history_profile") or {})
    required = {
        "target_node_id",
        "base_daily_demand",
        "demand_stddev",
        "zero_demand_probability",
        "annual_amplitude",
        "weekly_multipliers",
        "initial_inventory",
        "reorder_point",
        "reorder_quantity",
        "lead_time_mean_days",
        "lead_time_jitter_days",
        "shock_day",
        "shock_lead_time_add_days",
        "unit_cost_minor",
        "shock_cost_pass_through_pct",
    }
    missing = sorted(required - set(profile))
    if missing:
        raise ValueError(f"synthetic_history_profile_incomplete:{','.join(missing)}")
    weekly = list(profile["weekly_multipliers"])
    if len(weekly) != 7:
        raise ValueError("synthetic_history_weekly_profile_must_have_seven_days")

    rng = random.Random(int(seed))
    history_parameters = {
        "supply_scenario_parameter_hash": scenario["manifest"]["parameter_hash"],
        "days": int(days),
        "start_date": start_date.isoformat(),
    }
    history_parameter_hash = hashlib.sha256(
        _canonical(history_parameters).encode("utf-8"),
    ).hexdigest()
    history_provenance = [
        f"synthetic_supply/{scenario['manifest']['generator_version']}",
        f"scenario/{scenario_id}",
        f"history_parameter_hash/{history_parameter_hash}",
    ]
    on_hand = int(profile["initial_inventory"])
    purchase_orders: list[dict[str, Any]] = []
    daily_history: list[dict[str, Any]] = []
    shock_day = int(profile["shock_day"])
    base_cost = int(profile["unit_cost_minor"])
    shock_cost = int(round(base_cost * (
        1.0 + float(profile["shock_cost_pass_through_pct"]) / 100.0
    )))

    for day_index in range(days):
        current_date = start_date + timedelta(days=day_index)
        received = [
            po for po in purchase_orders if po["receipt_day"] == day_index
        ]
        receipt_units = sum(int(po["quantity_units"]) for po in received)
        opening_on_hand = on_hand
        on_hand += receipt_units

        seasonal = 1.0 + float(profile["annual_amplitude"]) * math.sin(
            2.0 * math.pi * day_index / 365.0
        )
        expected = max(
            0.0,
            float(profile["base_daily_demand"])
            * float(weekly[current_date.weekday()])
            * seasonal,
        )
        if rng.random() < float(profile["zero_demand_probability"]):
            latent_demand = 0
        else:
            latent_demand = max(
                0,
                int(round(rng.gauss(expected, float(profile["demand_stddev"])))),
            )
        observed_sales = min(on_hand, latent_demand)
        lost_sales = latent_demand - observed_sales
        on_hand -= observed_sales

        incoming = sum(
            int(po["quantity_units"])
            for po in purchase_orders
            if po["order_day"] <= day_index < po["receipt_day"]
        )
        if on_hand + incoming <= int(profile["reorder_point"]):
            lead_time = max(
                1,
                int(profile["lead_time_mean_days"])
                + (
                    int(profile["shock_lead_time_add_days"])
                    if day_index >= shock_day
                    else 0
                )
                + rng.randint(
                    -int(profile["lead_time_jitter_days"]),
                    int(profile["lead_time_jitter_days"]),
                ),
            )
            purchase_orders.append({
                "id": f"synthetic-po-{scenario_id}-{len(purchase_orders) + 1}",
                "target_node_id": str(profile["target_node_id"]),
                "order_day": day_index,
                "order_date": current_date.isoformat(),
                "receipt_day": day_index + lead_time,
                "planned_lead_time_days": lead_time,
                "quantity_units": int(profile["reorder_quantity"]),
                "unit_cost_minor": shock_cost if day_index >= shock_day else base_cost,
                "currency": "SYN",
                "authority": "simulation_only",
                "simulation_only": True,
                "provenance_chain": history_provenance,
            })

        daily_history.append({
            "date": current_date.isoformat(),
            "day_index": day_index,
            "target_node_id": str(profile["target_node_id"]),
            "opening_on_hand_units": opening_on_hand,
            "receipt_units": receipt_units,
            "latent_demand_units": latent_demand,
            "observed_sales_units": observed_sales,
            "lost_sales_units": lost_sales,
            "closing_on_hand_units": on_hand,
            "stockout_censored": lost_sales > 0,
            "authority": "simulation_only",
            "simulation_only": True,
        })

    total_latent = sum(row["latent_demand_units"] for row in daily_history)
    total_observed = sum(row["observed_sales_units"] for row in daily_history)
    manifest = {
        **scenario["manifest"],
        "parameter_hash": history_parameter_hash,
        "supply_scenario_parameter_hash": scenario["manifest"]["parameter_hash"],
        "history_days": days,
        "start_date": start_date.isoformat(),
        "shock_day": shock_day,
        "evidence_availability_clock": "event_time",
    }
    return {
        "manifest": manifest,
        "daily_history": daily_history,
        "purchase_orders": purchase_orders,
        "summary": {
            "latent_demand_units": total_latent,
            "observed_sales_units": total_observed,
            "lost_sales_units": total_latent - total_observed,
            "stockout_days": sum(
                1 for row in daily_history if row["stockout_censored"]
            ),
            "fill_rate": (
                round(total_observed / total_latent, 6)
                if total_latent
                else None
            ),
        },
    }
