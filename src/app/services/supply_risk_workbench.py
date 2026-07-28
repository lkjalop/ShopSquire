"""Tenant-scoped, read-only projection of causal synthetic supply evidence."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.app.services.market_source_registry import sources_for_signal
from src.app.services.supply_impact_reasoner import (
    build_grounded_impact_hypothesis,
    propose_procurement_options,
)
from src.app.services.synthetic_canonical_replay import materialize_canonical_replay
from src.app.services.synthetic_replay_acceptance import build_acceptance_report
from src.app.services.synthetic_replay_shadow import evaluate_shadow_decisions
from src.app.services.synthetic_supply_history import SCENARIO_PATH


def list_supply_risk_scenarios(
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    selected = Path(path).resolve() if path else SCENARIO_PATH
    payload = json.loads(selected.read_text(encoding="utf-8"))
    rows = []
    for scenario_id, scenario in sorted((payload.get("scenarios") or {}).items()):
        profile = dict(scenario.get("history_profile") or {})
        signals = list(scenario.get("signals") or [])
        rows.append({
            "scenario_id": scenario_id,
            "description": str(scenario.get("description") or ""),
            "target_node_id": profile.get("target_node_id"),
            "pestel_domains": sorted({
                domain
                for signal in signals
                for domain in signal.get("pestel_domains") or []
            }),
            "authority": "simulation_only",
        })
    return rows


def build_supply_risk_workbench(
    *,
    tenant_id: str,
    scenario_id: str,
    seed: int = 42,
    days: int = 400,
    decision_time: str | None = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("supply_risk_tenant_required")
    replay = materialize_canonical_replay(
        scenario_id,
        seed=int(seed),
        days=int(days),
        tenant_id=tenant,
    )
    at = decision_time or datetime.now(timezone.utc).isoformat()
    target = str(replay["profile"]["target_node_id"])
    hypothesis = build_grounded_impact_hypothesis(
        tenant_id=tenant,
        target_node_id=target,
        nodes=replay["supply"]["nodes"],
        edges=replay["supply"]["edges"],
        signals=replay["supply"]["signals"],
        decision_time=at,
    )
    options = propose_procurement_options(hypothesis)
    source_candidates: dict[str, list[dict[str, Any]]] = {}
    for signal in replay["supply"]["signals"]:
        signal_type = str(signal.get("signal_type") or "")
        source_candidates[signal_type] = [
            {
                "source_id": row["source_id"],
                "publisher": row["publisher"],
                "trust_tier": row["trust_tier"],
                "licence_id": row["licence_id"],
                "licence_url": row["licence_url"],
                "measurement_scope": row["measurement_scope"],
                "pestel_domains": row["pestel_domains"],
                "refresh_expectation": row.get("refresh_expectation"),
                "decision_authority": row["decision_authority"],
            }
            for row in sources_for_signal(signal_type)
        ]
    signals = []
    decision_stamp = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if decision_stamp.tzinfo is None:
        decision_stamp = decision_stamp.replace(tzinfo=timezone.utc)
    for signal in replay["supply"]["signals"]:
        available = datetime.fromisoformat(
            str(signal["available_at"]).replace("Z", "+00:00")
        )
        if available.tzinfo is None:
            available = available.replace(tzinfo=timezone.utc)
        signals.append({
            **signal,
            "freshness": {
                "available_at": available.astimezone(timezone.utc).isoformat(),
                "age_days": max(
                    0,
                    round(
                        (
                            decision_stamp.astimezone(timezone.utc)
                            - available.astimezone(timezone.utc)
                        ).total_seconds() / 86400,
                        2,
                    ),
                ),
                "status": "simulated",
            },
            "official_source_candidates": source_candidates.get(
                str(signal.get("signal_type") or ""),
                [],
            ),
        })
    scopes = {
        (
            str(signal.get("subject_node_id") or ""),
            str(signal.get("signal_type") or ""),
        )
        for signal in signals
    }
    contradiction = {
        "status": (
            "no_conflict_single_observation"
            if len(signals) <= 1
            else "comparable_review_required"
        ),
        "comparable_scope_count": len(scopes),
        "incomparable_scopes": [],
        "winner": None,
        "policy": "never collapse different geography, measurement, currency or UoM",
    }
    missing = list(hypothesis.get("missing_evidence") or [])
    if any(not rows for rows in source_candidates.values()):
        missing.append("registered_official_source_for_signal_type")
    completeness = {
        "dependency_path": bool(hypothesis.get("dependency_paths")),
        "signal_provenance": all(signal.get("provenance_chain") for signal in signals),
        "official_source_candidates": all(
            bool(rows) for rows in source_candidates.values()
        ),
        "supplier_confirmation": bool(
            hypothesis.get("supplier_confirmation_id")
        ),
        "missing_evidence": sorted(set(missing)),
    }
    return {
        "tenant_id": tenant,
        "scenario": replay["manifest"],
        "target_node_id": target,
        "authority": "simulation_only",
        "execution_allowed": False,
        "pestel_domains": sorted({
            domain
            for signal in signals
            for domain in signal.get("pestel_domains") or []
        }),
        "signals": signals,
        "dependency_paths": hypothesis.get("dependency_paths") or [],
        "impact": hypothesis.get("impact"),
        "confidence": hypothesis.get("confidence"),
        "causal_language": hypothesis.get("causal_language"),
        "alternatives": hypothesis.get("alternatives") or [],
        "completeness": completeness,
        "contradictions": contradiction,
        "procurement_options": options,
        "acceptance": build_acceptance_report(replay),
        "shadow_evaluation": evaluate_shadow_decisions(replay),
    }
