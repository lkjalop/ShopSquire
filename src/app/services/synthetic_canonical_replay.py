"""Materialize deterministic synthetic commerce histories as canonical events.

The output uses the same typed append-only observation contract as real feeds.
It is permanently labelled simulation-only and is never projected into an
authoritative operational read model.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.app.services.authoritative_business_feed import (
    BusinessObservation,
    business_observation_id,
)
from src.app.services.synthetic_supply_history import (
    SCENARIO_PATH,
    generate_commerce_history,
    generate_supply_scenario,
)


SOURCE = "synthetic_supply_replay"


def _stamp(day: str, *, hour: int = 0) -> str:
    parsed = datetime.fromisoformat(day).replace(
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=timezone.utc,
    )
    return parsed.isoformat()


def _observation(
    entity_type: str,
    external_id: str,
    event_time: str,
    payload: dict[str, Any],
    *,
    corrects: str | None = None,
    reverses: str | None = None,
) -> BusinessObservation:
    return BusinessObservation(
        entity_type=entity_type,
        external_id=external_id,
        event_time=event_time,
        payload=payload,
        corrects_observation_id=corrects,
        reverses_observation_id=reverses,
    )


def materialize_canonical_replay(
    scenario_id: str,
    *,
    seed: int,
    days: int,
    tenant_id: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("synthetic_replay_tenant_required")
    history = generate_commerce_history(
        scenario_id,
        seed=seed,
        days=days,
        path=path,
    )
    supply = generate_supply_scenario(scenario_id, seed=seed, path=path)
    for family in ("nodes", "edges", "signals"):
        for row in supply[family]:
            row["tenant_id"] = tenant
    selected = Path(path).resolve() if path else SCENARIO_PATH
    raw = json.loads(selected.read_text(encoding="utf-8"))
    profile = dict(
        ((raw.get("scenarios") or {}).get(scenario_id) or {}).get("history_profile")
        or {}
    )
    event_plan = dict(profile.get("event_plan") or {})
    target = str(profile["target_node_id"])
    supplier = next(
        (
            str(node["id"])
            for node in supply["nodes"]
            if node.get("node_type") == "supplier"
        ),
        "supplier:synthetic",
    )
    currency = "USD"
    location_a = "location:primary"
    location_b = "location:secondary"
    current_price = int(
        profile.get("current_price_minor")
        or round(int(profile["unit_cost_minor"]) * 1.5)
    )
    observations: list[BusinessObservation] = []

    first_date = history["daily_history"][0]["date"]
    initial = _observation(
        "inventory_adjustment",
        f"{scenario_id}:initial-balance",
        _stamp(first_date),
        {
            "variant_id": target,
            "location_id": location_a,
            "quantity_delta": int(profile["initial_inventory"]),
            "uom": "EA",
            "reason_code": "synthetic_opening_balance",
            "approved_by": "synthetic-generator",
        },
    )
    observations.append(initial)

    for day in history["daily_history"]:
        day_index = int(day["day_index"])
        date_value = str(day["date"])
        sold = int(day["observed_sales_units"])
        if sold:
            order_id = f"{scenario_id}:order:{day_index}"
            observations.extend([
                _observation(
                    "order",
                    order_id,
                    _stamp(date_value, hour=12),
                    {
                        "party_external_id": f"synthetic-party:{day_index % 17}",
                        "status": "fulfilled",
                        "total": {
                            "amount_minor": sold * current_price,
                            "currency": currency,
                        },
                    },
                ),
                _observation(
                    "order_line",
                    f"{order_id}:line:1",
                    _stamp(date_value, hour=12),
                    {
                        "order_external_id": order_id,
                        "variant_id": target,
                        "quantity": {"value": sold, "uom": "EA"},
                        "unit_price": {
                            "amount_minor": current_price,
                            "currency": currency,
                        },
                    },
                ),
            ])
        observations.append(_observation(
            "location_atp",
            f"{scenario_id}:atp:{day_index}",
            _stamp(date_value, hour=23),
            {
                "variant_id": target,
                "location_id": location_a,
                "source_atp": {
                    "value": int(day["closing_on_hand_units"]),
                    "uom": "EA",
                },
                "source_basis": [
                    "synthetic_opening_balance",
                    "synthetic_receipts",
                    "synthetic_observed_sales",
                ],
                "source_calculated_at": _stamp(date_value, hour=23),
                "ttl_seconds": 86400,
            },
        ))

    po_by_receipt_day: dict[int, dict[str, Any]] = {}
    quarantine_every = max(0, int(event_plan.get("inspection_quarantine_every") or 0))
    tolerance = int(event_plan.get("quantity_tolerance") or 0)
    for po_index, po in enumerate(history["purchase_orders"], start=1):
        po_id = str(po["id"])
        order_date = str(po["order_date"])
        quantity = int(po["quantity_units"])
        unit_cost = int(po["unit_cost_minor"])
        observations.append(_observation(
            "purchase_order",
            po_id,
            _stamp(order_date, hour=9),
            {
                "supplier_external_id": supplier,
                "status": "issued",
                "total": {
                    "amount_minor": quantity * unit_cost,
                    "currency": currency,
                },
            },
        ))
        receipt_day = int(po["receipt_day"])
        if receipt_day >= days:
            continue
        po_by_receipt_day[receipt_day] = po
        receipt_date = history["daily_history"][receipt_day]["date"]
        receipt_id = f"{po_id}:receipt"
        quarantined = bool(quarantine_every and po_index % quarantine_every == 0)
        custody = "quarantined" if quarantined else "accepted"
        observations.extend([
            _observation(
                "receipt",
                receipt_id,
                _stamp(receipt_date, hour=8),
                {
                    "purchase_order_external_id": po_id,
                    "variant_id": target,
                    "location_id": location_a,
                    "quantity": {"value": quantity, "uom": "EA"},
                    "custody_status": custody,
                    "ownership_status": "owned",
                    "unit_cost": {"amount_minor": unit_cost, "currency": currency},
                },
            ),
            _observation(
                "inspection",
                f"{receipt_id}:inspection",
                _stamp(receipt_date, hour=10),
                {
                    "receipt_external_id": receipt_id,
                    "variant_id": target,
                    "quantity": {"value": quantity, "uom": "EA"},
                    "outcome": "quarantined" if quarantined else "accepted",
                    "reason_code": (
                        "synthetic_condition_check"
                        if quarantined
                        else "synthetic_pass"
                    ),
                },
            ),
        ])
        invoice_id = f"{po_id}:invoice"
        invoiced_quantity = quantity
        observations.extend([
            _observation(
                "invoice",
                invoice_id,
                _stamp(receipt_date, hour=15),
                {
                    "party_external_id": supplier,
                    "status": "received",
                    "total": {
                        "amount_minor": invoiced_quantity * unit_cost,
                        "currency": currency,
                    },
                },
            ),
            _observation(
                "invoice_line",
                f"{invoice_id}:line:1",
                _stamp(receipt_date, hour=15),
                {
                    "invoice_external_id": invoice_id,
                    "purchase_order_external_id": po_id,
                    "receipt_external_ids": [receipt_id],
                    "variant_id": target,
                    "quantity": {"value": invoiced_quantity, "uom": "EA"},
                    "unit_cost": {
                        "amount_minor": unit_cost,
                        "currency": currency,
                    },
                },
            ),
            _observation(
                "procurement_reconciliation",
                f"{po_id}:reconciliation",
                _stamp(receipt_date, hour=16),
                {
                    "purchase_order_external_id": po_id,
                    "invoice_external_id": invoice_id,
                    "receipt_external_ids": [receipt_id],
                    "variant_id": target,
                    "ordered_quantity": {"value": quantity, "uom": "EA"},
                    "received_quantity": {"value": quantity, "uom": "EA"},
                    "invoiced_quantity": {
                        "value": invoiced_quantity,
                        "uom": "EA",
                    },
                    "quantity_tolerance": tolerance,
                    "ordered_unit_cost": {
                        "amount_minor": unit_cost,
                        "currency": currency,
                    },
                    "invoiced_unit_cost": {
                        "amount_minor": unit_cost,
                        "currency": currency,
                    },
                    "status": "matched",
                    "exception_reasons": [],
                },
            ),
        ])

    def planned_day(name: str, fallback: int) -> tuple[int, str]:
        index = min(days - 1, max(0, int(event_plan.get(name, fallback))))
        return index, str(history["daily_history"][index]["date"])

    transfer_day, transfer_date = planned_day("transfer_day", days // 4)
    observations.append(_observation(
        "transfer",
        f"{scenario_id}:transfer:{transfer_day}",
        _stamp(transfer_date, hour=11),
        {
            "variant_id": target,
            "from_location_id": location_a,
            "to_location_id": location_b,
            "quantity": {"value": 1, "uom": "EA"},
            "status": "received",
        },
    ))
    planned_return_day, _ = planned_day("return_day", days // 3)
    sale_days = [
        int(row["day_index"])
        for row in history["daily_history"]
        if int(row["observed_sales_units"]) > 0
    ]
    eligible_sale_days = [
        day_index for day_index in sale_days if day_index <= planned_return_day
    ]
    return_order_day = (
        eligible_sale_days[-1]
        if eligible_sale_days
        else sale_days[0] if sale_days else None
    )
    if return_order_day is None:
        raise ValueError("synthetic_return_requires_fulfilled_order")
    return_day = max(planned_return_day, return_order_day)
    return_date = str(history["daily_history"][return_day]["date"])
    observations.append(_observation(
        "return",
        f"{scenario_id}:return:{return_day}",
        _stamp(return_date, hour=14),
        {
            "order_external_id": f"{scenario_id}:order:{return_order_day}",
            "variant_id": target,
            "quantity": {"value": 1, "uom": "EA"},
            "physical_disposition": "quarantine",
            "financial_disposition": "refunded",
        },
    ))
    markdown_day, markdown_date = planned_day("markdown_day", int(days * 0.8))
    observations.append(_observation(
        "markdown",
        f"{scenario_id}:markdown:{markdown_day}",
        _stamp(markdown_date, hour=9),
        {
            "variant_id": target,
            "location_id": location_a,
            "original_price": {
                "amount_minor": current_price,
                "currency": currency,
            },
            "new_price": {
                "amount_minor": max(
                    int(profile["unit_cost_minor"]),
                    round(current_price * 0.9),
                ),
                "currency": currency,
            },
            "reason_code": "synthetic_stale_stock",
            "effective_at": _stamp(markdown_date, hour=9),
            "approved_by": "synthetic-policy",
        },
    ))
    disposal_day, disposal_date = planned_day("disposal_day", int(days * 0.9))
    observations.append(_observation(
        "disposal",
        f"{scenario_id}:disposal:{disposal_day}",
        _stamp(disposal_date, hour=10),
        {
            "variant_id": target,
            "location_id": location_a,
            "quantity": {"value": 1, "uom": "EA"},
            "reason_code": (
                "synthetic_expiry"
                if profile.get("shelf_life_days")
                else "synthetic_damage"
            ),
            "writeoff": {
                "amount_minor": int(profile["unit_cost_minor"]),
                "currency": currency,
            },
            "approved_by": "synthetic-policy",
        },
    ))

    correction_day, correction_date = planned_day("correction_day", days // 8)
    adjustment = _observation(
        "inventory_adjustment",
        f"{scenario_id}:cycle-count:{correction_day}",
        _stamp(correction_date, hour=10),
        {
            "variant_id": target,
            "location_id": location_a,
            "quantity_delta": -1,
            "uom": "EA",
            "reason_code": "synthetic_cycle_count",
            "approved_by": "synthetic-operator",
        },
    )
    observations.append(adjustment)
    adjustment_id = business_observation_id(
        tenant_id=tenant,
        source=SOURCE,
        observation=adjustment,
    )
    correction = _observation(
        "inventory_adjustment",
        f"{scenario_id}:cycle-count:{correction_day}:correction",
        _stamp(correction_date, hour=11),
        {
            "variant_id": target,
            "location_id": location_a,
            "quantity_delta": -2,
            "uom": "EA",
            "reason_code": "synthetic_cycle_count_corrected",
            "approved_by": "synthetic-operator",
        },
        corrects=adjustment_id,
    )
    observations.append(correction)
    correction_id = business_observation_id(
        tenant_id=tenant,
        source=SOURCE,
        observation=correction,
    )
    reversal_day, reversal_date = planned_day("reversal_day", correction_day + 1)
    observations.append(_observation(
        "inventory_adjustment",
        f"{scenario_id}:cycle-count:{reversal_day}:reversal",
        _stamp(reversal_date, hour=11),
        dict(correction.payload),
        reverses=correction_id,
    ))

    observations.sort(
        key=lambda row: (row.event_time, row.entity_type, row.external_id)
    )
    manifest = {
        **history["manifest"],
        "source": SOURCE,
        "tenant_id": tenant,
        "canonical_schema_version": 1,
        "event_count": len(observations),
        "authority": "simulation_only",
        "projection_allowed": False,
    }
    return {
        "manifest": manifest,
        "history": history,
        "supply": supply,
        "observations": observations,
        "profile": profile,
        "receipt_index": po_by_receipt_day,
    }
