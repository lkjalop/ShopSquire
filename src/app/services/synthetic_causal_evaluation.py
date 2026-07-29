"""Deterministic multi-cohort evaluation for synthetic supply histories.

The report keeps latent truth apart from evidence a decision-maker could have
seen. It is an evaluation artefact only: no result can grant execution
authority, make a causal claim, or increase autonomous procurement authority.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from src.app.services.synthetic_canonical_replay import (
    materialize_canonical_replay,
)
from src.app.services.synthetic_replay_shadow import evaluate_shadow_decisions


EVALUATOR_VERSION = "synthetic_causal_cohorts_v1"
_DIMENSIONS = (
    "archetype",
    "lifecycle_stage",
    "intermittency",
    "lead_time_regime",
    "disruption",
)


def _stamp(value: date, *, hour: int = 0) -> str:
    return datetime(
        value.year,
        value.month,
        value.day,
        hour=hour,
        tzinfo=timezone.utc,
    ).isoformat()


def _intermittency(zero_rate: float) -> str:
    if zero_rate >= 0.75:
        return "high"
    if zero_rate >= 0.25:
        return "moderate"
    return "low"


def _lead_time_regime(mean_days: float) -> str:
    if mean_days > 21:
        return "long"
    if mean_days > 7:
        return "medium"
    return "short"


def _dimensions(
    scenario_id: str,
    replay: dict[str, Any],
    declared: dict[str, dict[str, str]],
) -> dict[str, str]:
    profile = replay["profile"]
    history = replay["history"]["daily_history"]
    zero_rate = sum(
        int(row["latent_demand_units"]) == 0 for row in history
    ) / len(history)
    lead_times = [
        float(row["planned_lead_time_days"])
        for row in replay["history"]["purchase_orders"]
    ]
    mean_lead = (
        statistics.fmean(lead_times)
        if lead_times
        else float(profile["lead_time_mean_days"])
    )
    selected = declared.get(scenario_id, {})
    return {
        "archetype": str(selected.get("archetype") or scenario_id),
        "lifecycle_stage": str(
            selected.get("lifecycle_stage") or "undefined_not_declared"
        ),
        "intermittency": _intermittency(zero_rate),
        "lead_time_regime": _lead_time_regime(mean_lead),
        "disruption": (
            "lead_time_and_cost"
            if int(profile.get("shock_lead_time_add_days") or 0) > 0
            and float(profile.get("shock_cost_pass_through_pct") or 0) > 0
            else "none"
        ),
    }


def _truth_and_evidence(
    replay: dict[str, Any],
    *,
    include_adversarial: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    profile = replay["profile"]
    start = date.fromisoformat(replay["manifest"]["start_date"])
    evaluation_end = start + timedelta(
        days=int(replay["manifest"]["history_days"]) - 1,
    )
    shock_at = start + timedelta(days=int(profile["shock_day"]))
    truth = {
        "status": "known_by_generator",
        "authority": "simulation_only",
        "shock": {
            "occurred_at": _stamp(shock_at),
            "lead_time_add_days": int(profile["shock_lead_time_add_days"]),
            "cost_pass_through_pct": float(profile["shock_cost_pass_through_pct"]),
        },
        "available_to_policy_at_event_time": False,
        "occurred_within_evaluation": shock_at <= evaluation_end,
    }
    observed_at = shock_at + timedelta(days=1)
    published_at = observed_at + timedelta(days=2)
    available_at = published_at + timedelta(days=1)
    evidence = [{
        "id": "simulated-market-observation",
        "claim": "input conditions tightened",
        "observed_at": _stamp(observed_at),
        "published_at": _stamp(published_at),
        "available_at": _stamp(available_at),
        "supports_true_shock": True,
        "adversarial": False,
        "adversarial_kind": None,
        "authority": "simulation_only",
        "causal_claim_allowed": False,
        "available_within_evaluation": available_at <= evaluation_end,
    }]
    if include_adversarial:
        evidence.extend([
            {
                "id": "simulated-unrelated-correlate",
                "claim": "unrelated index moved in the same direction",
                "observed_at": _stamp(observed_at),
                "published_at": _stamp(published_at),
                "available_at": _stamp(available_at),
                "supports_true_shock": False,
                "adversarial": True,
                "adversarial_kind": "misleading_correlation",
                "authority": "simulation_only",
                "causal_claim_allowed": False,
                "available_within_evaluation": available_at <= evaluation_end,
            },
            {
                "id": "simulated-supplier-denial",
                "claim": "supplier reports no constraint",
                "observed_at": _stamp(observed_at + timedelta(days=1)),
                "published_at": _stamp(published_at + timedelta(days=1)),
                "available_at": _stamp(available_at + timedelta(days=1)),
                "supports_true_shock": False,
                "adversarial": True,
                "adversarial_kind": "contradictory_supplier_claim",
                "contradiction_group": "synthetic-shock-existence",
                "authority": "simulation_only",
                "causal_claim_allowed": False,
                "available_within_evaluation": (
                    available_at + timedelta(days=1) <= evaluation_end
                ),
            },
        ])
    return truth, evidence


def _coverage(
    runs: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        observed = [row for row in rows if row.get("status") == "observed"]
        weights = [int(row.get("evaluation_origins") or 0) for row in observed]
        denominator = sum(weights)
        empirical = (
            sum(
                float(row["empirical_coverage"]) * weight
                for row, weight in zip(observed, weights, strict=True)
            ) / denominator
            if denominator
            else None
        )
        return {
            "status": (
                "observed" if empirical is not None
                else "undefined_insufficient_calibration"
            ),
            "observed_runs": len(observed),
            "evaluation_origins": denominator,
            "nominal_coverage": 0.9,
            "empirical_coverage": (
                round(empirical, 6) if empirical is not None else None
            ),
            "aggregation": (
                "origin_weighted_mean" if empirical is not None else "undefined"
            ),
        }

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for dimension in _DIMENSIONS:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for run in runs:
            groups[run["dimensions"][dimension]].append(run)
        result[dimension] = {}
        for label, members in sorted(groups.items()):
            selected_rows = [
                run["forecast"]["selected_prediction_interval"]
                for run in members
                if run["forecast"]["selected_prediction_interval"].get("status")
                == "observed"
            ]
            selected_summary = summarize(selected_rows)
            if label.startswith("undefined_"):
                status = label
            elif not selected_rows:
                status = "undefined_insufficient_calibration"
            else:
                status = "observed"
            by_model = {}
            model_names = sorted({
                name
                for run in members
                for name in run["forecast"].get("models", {})
            })
            for model in model_names:
                by_model[model] = summarize([
                    run["forecast"]["models"][model]["prediction_interval"]
                    for run in members
                    if model in run["forecast"].get("models", {})
                ])
                if label.startswith("undefined_"):
                    by_model[model].update({
                        "status": "undefined_dimension_not_declared",
                        "empirical_coverage": None,
                        "aggregation": "undefined",
                    })
            result[dimension][label] = {
                "status": status,
                "runs": len(members),
                "observed_runs": selected_summary["observed_runs"],
                "evaluation_origins": selected_summary["evaluation_origins"],
                "nominal_coverage": 0.9,
                "empirical_coverage": (
                    None
                    if label.startswith("undefined_")
                    else selected_summary["empirical_coverage"]
                ),
                "aggregation": (
                    "undefined"
                    if label.startswith("undefined_")
                    else selected_summary["aggregation"]
                ),
                "by_model": by_model,
            }
    return result


def _mean(values: Iterable[float]) -> float | None:
    selected = list(values)
    return round(statistics.fmean(selected), 6) if selected else None


def _policy_aggregation(runs: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [
        run["policy"]
        for run in runs
        if run["policy"].get("status") == "observed"
    ]
    mappings = {
        "fill_rate": "fill_rate",
        "stockout_units": "lost_units",
        "gross_margin_minor": "gross_margin_minor",
        "working_capital_minor": "working_capital_minor",
        "service_impact": "service_impact",
        "waste_units": "waste_units",
        "waste_value_minor": "waste_value_minor",
    }
    metrics: dict[str, Any] = {}
    for output_name, source_name in mappings.items():
        baseline = [
            float(row["baseline"][source_name])
            for row in observed
        ]
        candidate = [
            float(row["candidate"][source_name])
            for row in observed
        ]
        metrics[output_name] = {
            "status": "observed" if observed else "undefined_no_valid_policy_runs",
            "baseline_mean": _mean(baseline),
            "candidate_mean": _mean(candidate),
            "delta_mean": _mean(
                candidate[index] - baseline[index]
                for index in range(len(baseline))
            ),
        }
    return {
        "status": (
            "partially_observed"
            if observed and len(observed) < len(runs)
            else "observed"
            if observed
            else "undefined_no_valid_policy_runs"
        ),
        "runs": len(runs),
        "observed_runs": len(observed),
        "metrics": metrics,
        "authority": "simulation_only",
        "execution_allowed": False,
        "causal_claim_allowed": False,
        "limitations": [
            "policies replay identical synthetic demand and lead-time sequences",
            "expiry waste uses deterministic FEFO lots and declared shelf life",
            "margin and working capital use declared price and base unit cost",
            "means can hide tail outcomes; inspect per-run records",
        ],
    }


def evaluate_scenario_cohorts(
    *,
    scenario_ids: Iterable[str],
    seeds: Iterable[int],
    days: int = 400,
    cohort_dimensions: dict[str, dict[str, str]] | None = None,
    include_adversarial: bool = True,
) -> dict[str, Any]:
    """Evaluate a deterministic scenario x seed matrix without granting authority."""
    scenarios = sorted({str(item).strip() for item in scenario_ids if str(item).strip()})
    selected_seeds = sorted({int(seed) for seed in seeds})
    if not scenarios:
        raise ValueError("synthetic_evaluation_scenarios_required")
    if not selected_seeds:
        raise ValueError("synthetic_evaluation_seeds_required")
    if days < 1:
        raise ValueError("synthetic_evaluation_days_must_be_positive")
    declared = cohort_dimensions or {}
    runs: list[dict[str, Any]] = []
    for scenario_id in scenarios:
        for seed in selected_seeds:
            replay = materialize_canonical_replay(
                scenario_id,
                seed=seed,
                days=days,
                tenant_id="synthetic-lab",
            )
            shadow = evaluate_shadow_decisions(replay)
            forecast = dict(shadow["forecast_evaluation"])
            forecast["evaluation_mode"] = forecast.get("authority")
            forecast["authority"] = "simulation_only"
            forecast["execution_allowed"] = False
            forecast["can_increase_autonomy"] = False
            truth, evidence = _truth_and_evidence(
                replay,
                include_adversarial=include_adversarial,
            )
            runs.append({
                "scenario_id": scenario_id,
                "seed": seed,
                "parameter_hash": replay["manifest"]["parameter_hash"],
                "dimensions": _dimensions(scenario_id, replay, declared),
                "latent_truth": truth,
                "observed_evidence": evidence,
                "forecast": forecast,
                "policy": shadow["policy_counterfactual"],
                "authority": "simulation_only",
                "execution_allowed": False,
                "can_increase_autonomy": False,
            })
    manifest_payload = {
        "version": EVALUATOR_VERSION,
        "scenarios": scenarios,
        "seeds": selected_seeds,
        "days": days,
        "include_adversarial": include_adversarial,
        "cohort_dimensions": declared,
    }
    manifest_hash = hashlib.sha256(
        json.dumps(
            manifest_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    ).hexdigest()
    return {
        "manifest": {
            **manifest_payload,
            "parameter_hash": manifest_hash,
            "run_count": len(runs),
        },
        "runs": runs,
        "conditional_interval_coverage": _coverage(runs),
        "policy_counterfactuals": _policy_aggregation(runs),
        "adversarial_evaluation": {
            "enabled": include_adversarial,
            "misleading_correlation_records": sum(
                item.get("adversarial_kind") == "misleading_correlation"
                for run in runs
                for item in run["observed_evidence"]
            ),
            "contradictory_supplier_records": sum(
                item.get("adversarial_kind") == "contradictory_supplier_claim"
                for run in runs
                for item in run["observed_evidence"]
            ),
            "can_increase_autonomy": False,
            "authority": "simulation_only",
        },
        "authority": "simulation_only",
        "execution_allowed": False,
        "causal_claim_allowed": False,
        "can_increase_autonomy": False,
    }
