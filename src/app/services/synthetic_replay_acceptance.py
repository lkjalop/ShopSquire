"""Acceptance gates for replayable synthetic commerce histories."""
from __future__ import annotations

import math
import statistics
from typing import Any

from src.app.services.authoritative_business_feed import business_observation_id
from src.app.services.forecast_intelligence import (
    compare_forecast_models,
    prediction_interval_coverage_report,
)
from src.app.services.synthetic_policy_counterfactual import (
    compare_inventory_policies,
)


def _gate(passed: bool, *, value: Any = None, detail: str | None = None) -> dict[str, Any]:
    return {
        "status": "passed" if passed else "failed",
        "value": value,
        "detail": detail,
    }


def build_acceptance_report(replay: dict[str, Any]) -> dict[str, Any]:
    history = list((replay.get("history") or {}).get("daily_history") or [])
    purchase_orders = list((replay.get("history") or {}).get("purchase_orders") or [])
    observations = list(replay.get("observations") or [])
    inventory_projection = dict(replay.get("inventory_projection") or {})
    profile = dict(replay.get("profile") or {})
    if not history:
        raise ValueError("synthetic_replay_history_required")

    conservation_failures = [
        row["day_index"]
        for row in history
        if int(row["closing_on_hand_units"]) != (
            int(row["opening_on_hand_units"])
            + int(row["receipt_units"])
            - int(row["observed_sales_units"])
        )
    ]
    order_failures = [
        index
        for index in range(len(observations) - 1)
        if observations[index].event_time > observations[index + 1].event_time
    ]
    external_ids = {
        (observation.entity_type, observation.external_id)
        for observation in observations
    }
    observation_ids = {
        business_observation_id(
            tenant_id=replay["manifest"]["tenant_id"],
            source=replay["manifest"]["source"],
            observation=observation,
        )
        for observation in observations
    }
    reference_failures: list[str] = []
    relation_fields = {
        "order_line": (("order", "order_external_id"),),
        "return": (("order", "order_external_id"),),
        "receipt": (("purchase_order", "purchase_order_external_id"),),
        "inspection": (("receipt", "receipt_external_id"),),
        "invoice_line": (
            ("invoice", "invoice_external_id"),
            ("purchase_order", "purchase_order_external_id"),
        ),
        "procurement_reconciliation": (
            ("invoice", "invoice_external_id"),
            ("purchase_order", "purchase_order_external_id"),
        ),
    }
    for observation in observations:
        for related_type, field in relation_fields.get(observation.entity_type, ()):
            related_id = str(observation.payload.get(field) or "")
            if not related_id or (related_type, related_id) not in external_ids:
                reference_failures.append(
                    f"{observation.entity_type}:{observation.external_id}:{field}"
                )
        for receipt_id in observation.payload.get("receipt_external_ids") or []:
            if ("receipt", str(receipt_id)) not in external_ids:
                reference_failures.append(
                    f"{observation.entity_type}:{observation.external_id}:"
                    "receipt_external_ids"
                )
        for relation_name, relation_id in (
            ("corrects", observation.corrects_observation_id),
            ("reverses", observation.reverses_observation_id),
        ):
            if relation_id and relation_id not in observation_ids:
                reference_failures.append(
                    f"{observation.entity_type}:{observation.external_id}:"
                    f"{relation_name}"
                )
    latent = [int(row["latent_demand_units"]) for row in history]
    observed = [int(row["observed_sales_units"]) for row in history]
    zero_rate = sum(value == 0 for value in latent) / len(latent)
    positive_indices = [index for index, value in enumerate(latent) if value > 0]
    intervals = [
        positive_indices[index] - positive_indices[index - 1]
        for index in range(1, len(positive_indices))
    ]
    mean = statistics.fmean(latent)
    variance = statistics.pvariance(latent) if len(latent) > 1 else 0.0
    demand_cv = math.sqrt(variance) / mean if mean > 0 else None
    shock_day = int(profile["shock_day"])
    before = [po for po in purchase_orders if int(po["order_day"]) < shock_day]
    after = [po for po in purchase_orders if int(po["order_day"]) >= shock_day]
    pre_lead = statistics.fmean(
        float(po["planned_lead_time_days"]) for po in before
    ) if before else None
    post_lead = statistics.fmean(
        float(po["planned_lead_time_days"]) for po in after
    ) if after else None
    pre_cost = statistics.fmean(
        float(po["unit_cost_minor"]) for po in before
    ) if before else None
    post_cost = statistics.fmean(
        float(po["unit_cost_minor"]) for po in after
    ) if after else None
    causal_pass = bool(
        pre_lead is not None
        and post_lead is not None
        and pre_cost is not None
        and post_cost is not None
        and post_lead > pre_lead
        and post_cost > pre_cost
    )

    forecast = compare_forecast_models(
        latent,
        lead_time_days=float(profile["lead_time_mean_days"]),
    )
    forecast_status = (
        "observed" if forecast.get("selected_model")
        else "undefined"
    )
    selected_model = forecast.get("selected_model")
    interval = prediction_interval_coverage_report(forecast)
    selected_interval = interval["selected"]
    selected_forecast = (forecast.get("models") or {}).get(selected_model) or {}
    if selected_interval.get("status") == "observed":
        candidate_reorder_point = (
            float(selected_forecast.get("horizon_units") or 0.0)
            + float(selected_interval.get("calibration_error_units") or 0.0)
        )
    else:
        candidate_reorder_point = None
    policy_counterfactual = compare_inventory_policies(
        replay,
        candidate_reorder_point=candidate_reorder_point,
        candidate_reorder_quantity=int(profile["reorder_quantity"]),
        candidate_label="selected_model_p90_reorder_point",
    )
    total_latent = sum(latent)
    total_observed = sum(observed)
    average_on_hand = statistics.fmean(
        int(row["closing_on_hand_units"]) for row in history
    )
    purchase_spend = sum(
        int(po["quantity_units"]) * int(po["unit_cost_minor"])
        for po in purchase_orders
    )
    structural = {
        "inventory_conservation": _gate(
            not conservation_failures,
            value={"failures": conservation_failures[:20]},
        ),
        "event_ordering": _gate(
            not order_failures,
            value={"failures": order_failures[:20]},
        ),
        "referential_integrity": _gate(
            not reference_failures,
            value={"failures": reference_failures[:20]},
        ),
        "canonical_internal_movement_conservation": _gate(
            (
                (inventory_projection.get("conservation") or {}).get("status")
                == "passed"
            ),
            value=inventory_projection.get("conservation"),
            detail=(
                "Transfers and custody reclassifications must net to zero; "
                "sales, receipts, returns, disposal and adjustments remain "
                "explicit external physical deltas."
            ),
        ),
        "latent_sales_separation": _gate(all(
            int(row["observed_sales_units"]) <= int(row["latent_demand_units"])
            and int(row["lost_sales_units"]) == (
                int(row["latent_demand_units"])
                - int(row["observed_sales_units"])
            )
            for row in history
        )),
    }
    warning = (
        forecast_status == "undefined"
        or interval["status"] != "observed"
        or policy_counterfactual["status"] != "observed"
        or (
            (inventory_projection.get("balance_integrity") or {}).get("status")
            != "passed"
        )
        or (
            (inventory_projection.get("atp_reconciliation") or {}).get("status")
            != "matched"
        )
    )
    return {
        "scenario_id": replay["manifest"]["scenario_id"],
        "authority": "simulation_only",
        "structural_fidelity": structural,
        "statistical_fidelity": {
            "zero_demand_rate": {"status": "observed", "value": round(zero_rate, 4)},
            "average_inter_demand_interval": {
                "status": "observed" if intervals else "undefined",
                "value": round(statistics.fmean(intervals), 4) if intervals else None,
            },
            "demand_mean": {"status": "observed", "value": round(mean, 4)},
            "demand_variance": {"status": "observed", "value": round(variance, 4)},
            "demand_coefficient_of_variation": {
                "status": "observed" if demand_cv is not None else "undefined",
                "value": round(demand_cv, 4) if demand_cv is not None else None,
            },
        },
        "causal_interventions": {
            "status": "passed" if causal_pass else "failed",
            "shock_day": shock_day,
            "pre_lead_time_mean": pre_lead,
            "post_lead_time_mean": post_lead,
            "pre_unit_cost_mean": pre_cost,
            "post_unit_cost_mean": post_cost,
        },
        "forecast_discrimination": {
            "status": forecast_status,
            "selected_model": forecast.get("selected_model"),
            "models": forecast.get("models"),
            "evaluation": forecast.get("evaluation"),
        },
        "prediction_interval_coverage": interval,
        "canonical_inventory_projection": {
            "authority": "shadow_only",
            "conservation": inventory_projection.get("conservation"),
            "balance_integrity": inventory_projection.get("balance_integrity"),
            "atp_reconciliation": inventory_projection.get("atp_reconciliation"),
        },
        "business_utility": {
            "status": "observed" if total_latent else "undefined_zero_demand",
            "fill_rate": round(total_observed / total_latent, 4)
            if total_latent else None,
            "stockout_units": total_latent - total_observed,
            "stockout_days": sum(int(row["lost_sales_units"]) > 0 for row in history),
            "average_on_hand_units": round(average_on_hand, 4),
            "purchase_spend_minor": purchase_spend,
        },
        "policy_counterfactual": policy_counterfactual,
        "overall_status": (
            "failed"
            if any(row["status"] == "failed" for row in structural.values())
            or not causal_pass
            else "passed_with_warnings" if warning
            else "passed"
        ),
    }
