"""Universal finalization for typed recommendation-facade responses."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from src.app.deps import security_sanitize
from src.app.services.decision_log import log_decision, log_trace_event

logger = logging.getLogger("shopsquire.recommendation_finalizer")


def _products(payload: Dict[str, Any]) -> list[dict[str, Any]]:
    for candidate in (
        payload.get("products"), payload.get("results"),
        (payload.get("proposal") or {}).get("results") if isinstance(payload.get("proposal"), dict) else None,
    ):
        if isinstance(candidate, list):
            return [dict(item) for item in candidate if isinstance(item, dict)]
    return []


def finalize_core_response(
    payload: Dict[str, Any], trace_id: Optional[str], *, query: str = "",
    tenant_id: str = "default", uid: str = "",
) -> Dict[str, Any]:
    """Sanitize and persist one core response without importing the legacy router."""
    try:
        out = security_sanitize(dict(payload or {}))
    except Exception:
        logger.exception("core response sanitization failed")
        out = dict(payload or {})
    if not trace_id:
        return out

    out["trace_id"] = trace_id
    out["decision_trace_id"] = trace_id
    out.setdefault("decision_id", trace_id)
    products = _products(out)[:8]
    summary = [
        {
            "sku": str(item.get("sku") or ""),
            "name": str(item.get("name") or item.get("title") or ""),
            "price": item.get("price"),
            "price_cents": item.get("price_cents"),
            "currency": item.get("currency"),
            "reason_codes": list(item.get("reason_codes") or [])[:3],
            "reasons": [str(reason) for reason in (item.get("why") or item.get("reasons") or [])][:5],
            "score_norm": item.get("score_norm"),
            "workload_fit": item.get("workload_fit") if isinstance(item.get("workload_fit"), dict) else None,
        }
        for item in products
    ]
    canonical_identity = {
        "trace_id": trace_id,
        "ordered_skus": [item["sku"] for item in summary if item.get("sku")],
    }
    out["canonical_identity"] = canonical_identity
    right_panel = out.get("right_panel") if isinstance(out.get("right_panel"), dict) else {}
    try:
        right_panel = json.loads(json.dumps(right_panel, default=str))
    except Exception:
        right_panel = {"mode": str(right_panel.get("mode") or "")}
    right_panel.setdefault("anchor_sections", [])
    right_panel["canonical_identity"] = canonical_identity
    out["right_panel"] = right_panel
    lane = str(out.get("turn_intent") or "").strip().upper() or None
    routing_source = str(out.get("routing_source") or "").strip() or None
    decision = out.get("decision") if isinstance(out.get("decision"), dict) else {}
    constraints = (
        dict(out.get("constraints_used") or {})
        if isinstance(out.get("constraints_used"), dict)
        else {}
    )
    execution_steps = [dict(item) for item in (out.get("execution_steps") or [])
                       if isinstance(item, dict)][:24]
    security = dict(out.get("security") or {}) if isinstance(out.get("security"), dict) else {}
    security.setdefault("policy_route", "allow")
    security.setdefault("checked_boundary", "recommendation_facade")
    security.setdefault(
        "has_image",
        bool(out.get("image_security") or out.get("image_observations")
             or out.get("multimodal_fusion")),
    )
    intent_analysis = {
        "intent": lane,
        "lane": lane,
        "routing_source": routing_source,
        "subject_action": decision.get("subject_action"),
        "procurement_context": decision.get("procurement_context"),
        "use_case_key": constraints.get("use_case"),
        "workloads": constraints.get("workloads") or [],
        "requirements": constraints.get("requirements") or {},
        "budget_min": constraints.get("budget_min"),
        "budget_max": constraints.get("budget_max"),
        "quantity": constraints.get("order_quantity") or out.get("requested_quantity"),
        "currency": constraints.get("currency"),
    }
    evidence_items = [
        {"type": "candidate", "id": item["sku"], "score": 1.0}
        for item in summary if item.get("sku")
    ]
    if out.get("policy_answered") and out.get("policy_source"):
        evidence_items.append({
            "type": "policy",
            "id": str(out.get("policy_source")),
            "score": 1.0,
        })

    try:
        log_trace_event(
            trace_id=trace_id, event_type="recommendation_result", source_type="stage",
            source_id="Trace_Persistence", target_type="ui", target_id="right_panel",
            payload={"products_summary": summary, "right_panel_contract": right_panel,
                     "canonical_identity": canonical_identity,
                     "execution_mode": str(out.get("execution_mode") or "v2_served"),
                     "intent_analysis": intent_analysis, "constraints_used": constraints,
                     "execution_steps": execution_steps, "security": security},
        )
        persisted = log_decision(
            agent_name="Recommendation_Core",
            input_data={"query": str(query or "")[:1000], "intent": intent_analysis},
            retrieved_context={
                "agent_chain": out.get("agent_chain") or [],
                "products_count": len(summary),
                "right_panel_contract": right_panel,
                "intent_analysis": intent_analysis,
                "execution_steps": execution_steps,
            },
            proposed_action={
                "decision_mode": str(out.get("decision_mode") or "catalog_recommendation"),
                "execution_mode": str(out.get("execution_mode") or "v2_served"),
                "products_summary": summary,
                "results": summary,
                "canonical_identity": canonical_identity,
                "right_panel_contract": right_panel,
                "reasoning": out.get("assistant_message") or out.get("message"),
                "intent_analysis": intent_analysis,
                "constraints_used": constraints,
                "security": security,
                "evidence_items": evidence_items,
            },
            decision_id=trace_id, tenant_id=str(tenant_id or "default"),
            actor_id=str(uid or "") or None, actor_role="buyer",
            event_type="recommendation_result",
        )
        out["_trace_recommendation_persisted"] = bool(persisted)
    except Exception as exc:
        out["_trace_recommendation_persisted"] = False
        logger.warning("core response trace persistence failed for %s: %s", trace_id, exc)
    return out
