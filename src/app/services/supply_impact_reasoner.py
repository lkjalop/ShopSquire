"""Bounded dependency-path reasoning for advisory supply impacts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _paths(
    edges: list[dict[str, Any]], source: str, target: str, *, max_depth: int = 6,
) -> list[list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge.get("from_node_id") or ""), []).append(edge)
    found: list[list[dict[str, Any]]] = []

    def visit(node: str, path: list[dict[str, Any]], seen: set[str]) -> None:
        if len(path) >= max_depth:
            return
        for edge in adjacency.get(node, []):
            nxt = str(edge.get("to_node_id") or "")
            if not nxt or nxt in seen:
                continue
            candidate = path + [edge]
            if nxt == target:
                found.append(candidate)
            else:
                visit(nxt, candidate, seen | {nxt})

    visit(source, [], {source})
    return found


def _edge_factor(path: list[dict[str, Any]], key: str) -> float:
    value = 1.0
    for edge in path:
        value *= max(0.0, min(1.0, float(edge.get(key, 1.0))))
    return value


def build_grounded_impact_hypothesis(
    *,
    tenant_id: str,
    target_node_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    decision_time: str,
) -> dict[str, Any]:
    """Build an evidence bundle; never infer exposure without a graph path."""
    tenant = str(tenant_id or "").strip()
    target = str(target_node_id or "").strip()
    at = _time(decision_time)
    if not tenant or not target or at is None:
        raise ValueError("supply_impact_scope_required")
    node_ids = {str(node.get("id") or "") for node in nodes}
    if target not in node_ids:
        return _no_exposure(tenant, target, "target_not_in_supply_graph")
    eligible_edges = [
        edge for edge in edges
        if str(edge.get("tenant_id") or tenant) == tenant
        and (_time(edge.get("valid_from")) is None or _time(edge.get("valid_from")) <= at)
        and (_time(edge.get("valid_to")) is None or _time(edge.get("valid_to")) > at)
    ]
    active_signals = [
        signal for signal in signals
        if str(signal.get("tenant_id") or tenant) == tenant
        and signal.get("status") in {"observed", "simulated", "estimated"}
        and (_time(signal.get("available_at")) is None or _time(signal.get("available_at")) <= at)
        and str(signal.get("signal_type") or "") != "supplier_confirmation"
    ]
    path_rows = []
    low_total = high_total = 0.0
    confidence_values: list[float] = []
    for signal in active_signals:
        source = str(signal.get("subject_node_id") or "")
        for path in _paths(eligible_edges, source, target):
            low = max(0.0, float(signal.get("magnitude_low_pct") or 0.0))
            high = max(low, float(signal.get("magnitude_high_pct") or low))
            low *= _edge_factor(path, "cost_share_low") * _edge_factor(
                path, "pass_through_low",
            )
            high *= _edge_factor(path, "cost_share_high") * _edge_factor(
                path, "pass_through_high",
            )
            path_confidence = min(
                [float(signal.get("confidence") or 0.0)]
                + [float(edge.get("confidence") or 0.0) for edge in path]
            )
            confidence_values.append(path_confidence)
            low_total += low
            high_total += high
            path_rows.append({
                "signal_id": signal.get("id"),
                "signal_type": signal.get("signal_type"),
                "edge_ids": [edge.get("id") for edge in path],
                "node_path": [source] + [edge.get("to_node_id") for edge in path],
                "estimated_landed_cost_change_pct": {
                    "low": round(low, 4), "high": round(high, 4),
                },
                "confidence": round(path_confidence, 4),
            })
    if not path_rows:
        return _no_exposure(tenant, target, "no_time_valid_dependency_path")
    signal_ids = {str(row["signal_id"]) for row in path_rows}
    confirmation = next(
        (
            signal for signal in signals
            if signal.get("signal_type") == "supplier_confirmation"
            and signal_ids.intersection(
                {str(item) for item in signal.get("confirms_signal_ids") or []}
            )
            and signal.get("source_record_id")
            and signal.get("provenance_chain")
        ),
        None,
    )
    missing = [] if confirmation else [
        "supplier_cost_breakdown",
        "contract_pass_through_confirmation",
    ]
    return {
        "tenant_id": tenant,
        "target_node_id": target,
        "decision_time": at.isoformat(),
        "status": "supported_hypothesis",
        "causal_language": (
            "supplier_confirmed_exposure" if confirmation else "consistent_with"
        ),
        "dependency_paths": path_rows,
        "supporting_signal_ids": sorted(signal_ids),
        "supplier_confirmation_id": confirmation.get("id") if confirmation else None,
        "impact": {
            "landed_cost_change_pct": {
                "low": round(low_total, 4),
                "high": round(high_total, 4),
            },
            "availability_direction": (
                "down"
                if any(row["signal_type"] == "capacity_constraint" for row in path_rows)
                else "unknown"
            ),
            "magnitude_status": "bounded_estimate",
        },
        "confidence": round(min(confidence_values), 4),
        "alternatives": [
            "foreign_exchange_movement",
            "freight_or_energy_change",
            "supplier_margin_or_contract_change",
        ],
        "missing_evidence": missing,
        "authority": "advisory_only",
        "execution_allowed": False,
    }


def _no_exposure(tenant: str, target: str, reason: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "target_node_id": target,
        "status": "no_verified_exposure",
        "reason": reason,
        "dependency_paths": [],
        "impact": None,
        "authority": "advisory_only",
        "execution_allowed": False,
    }


def propose_procurement_options(hypothesis: dict[str, Any]) -> dict[str, Any]:
    if hypothesis.get("status") != "supported_hypothesis":
        return {
            "status": "not_proposed",
            "options": [],
            "authority": "proposal_only",
            "execution_allowed": False,
            "human_approval_required": True,
        }
    options = [
        {
            "action_type": "request_supplier_confirmation",
            "tradeoffs": ["adds decision latency", "improves causal and commercial evidence"],
            "requires_human_approval": True,
        },
        {
            "action_type": "source_qualified_alternative",
            "tradeoffs": [
                "may reduce concentration risk",
                "requires compatibility and certification checks",
            ],
            "requires_human_approval": True,
        },
        {
            "action_type": "monitor",
            "tradeoffs": ["avoids premature commitment", "retains shortage and price risk"],
            "requires_human_approval": False,
        },
    ]
    if hypothesis.get("impact", {}).get("availability_direction") == "down":
        options.insert(2, {
            "action_type": "review_buffer_or_timing",
            "tradeoffs": ["may improve service level", "may increase working capital"],
            "requires_human_approval": True,
        })
    return {
        "status": "human_review_required",
        "target_node_id": hypothesis.get("target_node_id"),
        "hypothesis_status": hypothesis.get("status"),
        "options": options,
        "authority": "proposal_only",
        "execution_allowed": False,
        "human_approval_required": True,
    }

