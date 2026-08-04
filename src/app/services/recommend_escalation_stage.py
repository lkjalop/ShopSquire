"""Escalation / human-in-the-loop decoration stage (extracted from suggest()).

Folds the risk / complexity / order / B2B signals into ONE deterministic escalation decision and surfaces
it on the payload: ``b2b_assessment``, ``escalation_assessment``, and — when the band is review /
human_required — ``needs_human_review`` + an ``escalation`` envelope + an incident for the review room.

Deterministic and non-raising: the injected assessors (assess_escalation, decompose, assess_b2b_intent)
never raise, so the stage carries NO try/except — identical to the inline block and friendly to the
recommend.py silent-except ratchet. Mutates ``payload`` in place. Vertical-blind.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List


def decorate_escalation(
    payload: Dict[str, Any],
    *,
    constraints: Dict[str, Any],
    analysis: Any,
    results: Any,
    query: Any,
    claim_guard_result: Any,
    trace_id: Any,
    uid: Any,
    assess_escalation: Callable[..., Any],
    decompose: Callable[[Any], Any],
    assess_b2b_intent: Callable[..., Any],
    auto_create_incident: Callable[..., Any],
) -> None:
    """Compute + surface the escalation decision on payload. Mutates payload in place; returns None."""
    _esc_cstat = constraints.get("constraint_status") if isinstance(constraints.get("constraint_status"), dict) else {}
    _esc_qty = constraints.get("order_quantity")
    _esc_qty = int(_esc_qty) if isinstance(_esc_qty, int) else 1
    _esc_risk = (analysis.get("details") or {}).get("risk_adj") if isinstance(analysis, dict) else None
    _esc_risk = float(_esc_risk) if isinstance(_esc_risk, (int, float)) else 0.0
    if _esc_risk > 1.0:
        _esc_risk = min(1.0, _esc_risk / 100.0)
    _esc_value = 0
    if isinstance(results, list) and results and isinstance(results[0], dict):
        _esc_p0 = results[0].get("price_cents")
        _esc_value = int(_esc_p0) * _esc_qty if isinstance(_esc_p0, int) else 0
    _esc_horizon = constraints.get("availability_horizon_days")
    _esc_rush = bool(isinstance(_esc_horizon, int) and 0 < _esc_horizon <= 7)
    # Intent-aware B2B: quantity is a SIGNAL, not a gate. Anomalous (absurd count) escalates HARD;
    # ambiguous-bulk gets B2B review treatment. Surfaced for pricing + the escalation room.
    _b2b = assess_b2b_intent(query, quantity=_esc_qty)
    payload["b2b_assessment"] = _b2b.to_dict()
    _esc_anom = (_b2b.verdict == "anomalous")
    _esc_decision = assess_escalation(
        decomposition_confidence=getattr(decompose(query), "decomposition_confidence", 1.0),
        irreversible_action=_esc_anom,
        order_quantity=_esc_qty,
        order_value_cents=_esc_value,
        fraud_score=max(_esc_risk, 0.75 if _esc_anom else 0.0),
        constraint_conflict=(_esc_cstat.get("exact_match") is False),
        claim_guard_rejected=(claim_guard_result == "fell_back_to_deterministic"),
        b2b=_b2b.wants_procurement_questions,
        rush_delivery=_esc_rush,
        review_requested=(_b2b.verdict == "ambiguous_bulk"),
    )
    payload["escalation_assessment"] = _esc_decision.to_dict()
    if _esc_decision.band in {"review", "human_required"}:
        payload["needs_human_review"] = True
        _esc_env = payload.get("escalation") if isinstance(payload.get("escalation"), dict) else {}
        if not _esc_env.get("route"):
            payload["escalation"] = {
                "route": "human_review",
                "reason": (_esc_decision.reasons[0] if _esc_decision.reasons else "ai_flagged_human_review"),
                "reasons": list(_esc_decision.reasons),
                "talk_to_client": _esc_decision.talk_to_client,
                "band": _esc_decision.band,
                "blocking": _esc_decision.band == "human_required",
                "approval_required": bool(payload.get("approval_id"))
                or _esc_decision.band == "human_required",
            }
        auto_create_incident(
            payload=payload, trace_id=trace_id, uid=uid, query=query,
            severity=("high" if _esc_decision.band == "human_required" else "warn"),
            source="recommend_escalation",
            extra_context={"escalation_assessment": _esc_decision.to_dict()},
        )
