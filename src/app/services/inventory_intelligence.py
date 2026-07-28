from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InventoryHistory:
    on_hand_units: int
    units_sold: int
    history_days: int
    gross_margin_cents: int
    average_inventory_cost_cents: int
    current_price_cents: int
    unit_cost_cents: int
    days_since_last_sale: int
    lead_time_days: float
    lead_time_stddev_days: float = 0.0


def calculate_inventory_intelligence(
    history: InventoryHistory,
    *,
    margin_floor_ratio: float = 0.15,
    stale_after_days: int = 90,
) -> dict[str, Any]:
    days = max(1, int(history.history_days))
    weekly_velocity = max(0.0, float(history.units_sold) * 7.0 / days)
    weeks_of_supply = (
        round(float(history.on_hand_units) / weekly_velocity, 3)
        if weekly_velocity > 0
        else None
    )
    annualisation = 365.0 / days
    gmroi = (
        round(
            float(history.gross_margin_cents) * annualisation
            / float(history.average_inventory_cost_cents),
            4,
        )
        if history.average_inventory_cost_cents > 0
        else None
    )
    safety_lead_days = max(
        0.0, float(history.lead_time_days) + 1.65 * float(history.lead_time_stddev_days)
    )
    reorder_point_units = round(weekly_velocity / 7.0 * safety_lead_days)
    floor_price = round(
        float(history.unit_cost_cents) * (1.0 + max(0.0, margin_floor_ratio))
    )
    stale = int(history.days_since_last_sale) >= max(1, int(stale_after_days))
    proposed_price = None
    if stale and history.current_price_cents > floor_price:
        proposed_price = max(floor_price, round(history.current_price_cents * 0.9))
    return {
        "weekly_shelf_velocity": round(weekly_velocity, 4),
        "weeks_of_supply": weeks_of_supply,
        "gmroi_annualised": gmroi,
        "reorder_point_units": reorder_point_units,
        "stale_stock": stale,
        "stale_price_proposal": (
            {
                "mode": "shadow",
                "current_price_cents": history.current_price_cents,
                "proposed_price_cents": proposed_price,
                "margin_floor_cents": floor_price,
                "execution_allowed": False,
            }
            if proposed_price is not None
            else None
        ),
    }
