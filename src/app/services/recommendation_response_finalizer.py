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
            "name": str(item.get("name") or ""),
            "price": item.get("price"),
            "price_cents": item.get("price_cents"),
            "currency": item.get("currency"),
            "reason_codes": list(item.get("reason_codes") or [])[:3],
        }
        for item in products
    ]
    right_panel = out.get("right_panel") if isinstance(out.get("right_panel"), dict) else {}
    try:
        right_panel = json.loads(json.dumps(right_panel, default=str))
    except Exception:
        right_panel = {"mode": str(right_panel.get("mode") or "")}
    right_panel.setdefault("anchor_sections", [])

    try:
        log_trace_event(
            trace_id=trace_id, event_type="recommendation_result", source_type="agent",
            source_id="Trace_Persistence_Agent", target_type="ui", target_id="right_panel",
            payload={"products_summary": summary, "right_panel_contract": right_panel},
        )
        persisted = log_decision(
            agent_name="Recommendation_Agent",
            input_data={"query": str(query or "")[:1000]},
            retrieved_context={
                "agent_chain": out.get("agent_chain") or [],
                "products_count": len(summary),
                "right_panel_contract": right_panel,
            },
            proposed_action={
                "decision_mode": str(out.get("decision_mode") or "catalog_recommendation"),
                "products_summary": summary,
                "right_panel_contract": right_panel,
                "reasoning": out.get("assistant_message") or out.get("message"),
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
