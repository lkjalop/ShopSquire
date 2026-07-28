"""Run governed inventory and supplier calculations against synthetic replay."""
from __future__ import annotations

import statistics
from typing import Any

from src.app.services.inventory_intelligence import (
    InventoryHistory,
    calculate_inventory_intelligence,
)
from src.app.services.procurement_decision_context import calculate_replenishment
from src.app.services.supplier_intelligence import supplier_shadow_score


def evaluate_shadow_decisions(replay: dict[str, Any]) -> dict[str, Any]:
    history = list((replay.get("history") or {}).get("daily_history") or [])
    purchase_orders = list((replay.get("history") or {}).get("purchase_orders") or [])
    profile = dict(replay.get("profile") or {})
    supply = dict(replay.get("supply") or {})
    if not history:
        raise ValueError("synthetic_replay_history_required")
    demand = [float(row["latent_demand_units"]) for row in history]
    lead_times = [float(po["planned_lead_time_days"]) for po in purchase_orders]
    current_atp = int(history[-1]["closing_on_hand_units"])
    incoming = sum(
        int(po["quantity_units"])
        for po in purchase_orders
        if int(po["receipt_day"]) >= len(history)
    )
    replenishment = calculate_replenishment({
        "demand": {
            "mean_daily": statistics.fmean(demand),
            "variance_daily": statistics.pvariance(demand),
            "distribution": "synthetic_empirical",
            "forecast_evaluation_id": replay["manifest"]["parameter_hash"],
        },
        "supplier_lead_time": {
            "mean_days": statistics.fmean(lead_times) if lead_times else float(
                profile["lead_time_mean_days"]
            ),
            "variance_days2": statistics.pvariance(lead_times)
            if len(lead_times) > 1 else 0.0,
        },
        "service_level": 0.95,
        "inventory": {
            "current_atp": current_atp,
            "incoming_supply": incoming,
        },
        "commercial": {
            "moq": int(profile["reorder_quantity"]),
            "pack_size": 1,
            "price_breaks": [],
        },
        "uom": {
            "base_uom": "EA",
            "order_uom": "EA",
            "factor_to_base": 1,
        },
        "source_authority": "simulation",
        "provenance": {
            "scenario_id": replay["manifest"]["scenario_id"],
            "parameter_hash": replay["manifest"]["parameter_hash"],
        },
    })
    replenishment["execution_allowed"] = False
    replenishment["authority"] = "shadow_only"

    supplier_id = next(
        (
            str(node["id"])
            for node in supply.get("nodes") or []
            if node.get("node_type") == "supplier"
        ),
        "supplier:synthetic",
    )
    supplier_events = []
    for index, po in enumerate(purchase_orders):
        receipt_day = int(po["receipt_day"])
        if receipt_day >= len(history):
            continue
        planned = int(po["planned_lead_time_days"])
        supplier_events.append({
            "tenant_id": replay["manifest"]["tenant_id"],
            "supplier_id": supplier_id,
            "event_type": "delivery",
            "source_record_id": po["id"],
            "requested_qty": int(po["quantity_units"]),
            "filled_qty": int(po["quantity_units"]),
            "received_qty": int(po["quantity_units"]),
            "rejected_qty": 1 if index and index % 7 == 0 else 0,
            "on_time": index % 5 != 0,
            "lead_time_days": planned,
            "price_index": int(po["unit_cost_minor"])
            / float(profile["unit_cost_minor"]),
            "currency_comparable": True,
            "uom_comparable": True,
            "realized_outcome": 1.0 if index % 5 != 0 else 0.0,
        })
    supplier = supplier_shadow_score(
        tenant_id=replay["manifest"]["tenant_id"],
        supplier_id=supplier_id,
        events=supplier_events,
        minimum_deliveries=5,
    )

    unit_cost = int(profile["unit_cost_minor"])
    current_price = int(profile.get("current_price_minor") or round(unit_cost * 1.5))
    sold = sum(int(row["observed_sales_units"]) for row in history)
    gross_margin = sold * max(0, current_price - unit_cost)
    average_inventory_cost = round(
        statistics.fmean(int(row["closing_on_hand_units"]) for row in history)
        * unit_cost
    )
    sale_days = [
        int(row["day_index"]) for row in history if int(row["observed_sales_units"]) > 0
    ]
    inventory = calculate_inventory_intelligence(
        InventoryHistory(
            on_hand_units=current_atp,
            units_sold=sold,
            history_days=len(history),
            gross_margin_cents=gross_margin,
            average_inventory_cost_cents=average_inventory_cost,
            current_price_cents=current_price,
            unit_cost_cents=unit_cost,
            days_since_last_sale=(
                len(history) - 1 - sale_days[-1] if sale_days else len(history)
            ),
            lead_time_days=statistics.fmean(lead_times) if lead_times else float(
                profile["lead_time_mean_days"]
            ),
            lead_time_stddev_days=statistics.pstdev(lead_times)
            if len(lead_times) > 1 else 0.0,
        ),
    )
    return {
        "scenario_id": replay["manifest"]["scenario_id"],
        "authority": "shadow_only",
        "execution_allowed": False,
        "replenishment": replenishment,
        "supplier_score": supplier,
        "inventory": inventory,
    }
