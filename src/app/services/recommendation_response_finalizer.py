"""Universal finalization for typed recommendation-facade responses."""
from __future__ import annotations

import json
import logging
import time
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
    finalization_started = time.perf_counter()
    sanitize_started = time.perf_counter()
    try:
        out = security_sanitize(dict(payload or {}))
    except Exception:
        logger.exception("core response sanitization failed")
        out = dict(payload or {})
    timing = dict(out.get("timing_breakdown") or {})
    timing["sanitize_ms"] = round((time.perf_counter() - sanitize_started) * 1000.0, 1)
    out["timing_breakdown"] = timing
    if not trace_id:
        timing["trace_persist_ms"] = 0.0
        timing["market_projection_ms"] = 0.0
        timing["finalization_ms"] = round(
            (time.perf_counter() - finalization_started) * 1000.0, 1,
        )
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
    shelf = out.get("shelf") if isinstance(out.get("shelf"), dict) else {}
    shelf_bands = shelf.get("bands") if isinstance(shelf.get("bands"), list) else []
    if not right_panel["anchor_sections"] and summary and not shelf_bands:
        right_panel["anchor_sections"] = [{
            "title": "Authorized recommendation",
            "match_basis": ["catalog eligibility", "budget", "capability"],
            "summary": (
                "Products shown after deterministic catalog, budget, and capability checks."
            ),
            "top_products": [
                {
                    "sku": item["sku"],
                    "name": item["name"],
                    "currency": item.get("currency"),
                    "price": item.get("price"),
                    "price_cents": item.get("price_cents"),
                    "score_norm": item.get("score_norm"),
                    "reasons": item.get("reasons") or [],
                }
                for item in summary[:3]
            ],
        }]
    right_panel["canonical_identity"] = canonical_identity
    right_panel["semantic_resolution"] = out.get("semantic_resolution")
    right_panel["semantic_evidence"] = out.get("semantic_evidence")
    right_panel["catalog_alignment"] = out.get("catalog_alignment")
    right_panel["case_obligations"] = out.get("case_obligations")
    right_panel["explanation"] = (
        dict(out.get("explanation") or {})
        if isinstance(out.get("explanation"), dict)
        else None
    )
    out["right_panel"] = right_panel
    lane = str(out.get("turn_intent") or "").strip().upper() or None
    routing_source = str(out.get("routing_source") or "").strip() or None
    decision = out.get("decision") if isinstance(out.get("decision"), dict) else {}
    constraints = (
        dict(out.get("constraints_used") or {})
        if isinstance(out.get("constraints_used"), dict)
        else {}
    )
    intent_details = (
        dict(out.get("intent") or {})
        if isinstance(out.get("intent"), dict)
        else {}
    )
    title_requirements = (
        dict(intent_details.get("title_requirements") or {})
        if isinstance(intent_details.get("title_requirements"), dict)
        else {}
    )
    workload_evidence = (
        dict(title_requirements.get("external_workload_evidence") or {})
        if isinstance(title_requirements.get("external_workload_evidence"), dict)
        else {}
    )
    budget_min_cents = constraints.get("budget_min_cents")
    budget_max_cents = constraints.get("budget_max_cents")
    execution_steps = [dict(item) for item in (out.get("execution_steps") or [])
                       if isinstance(item, dict)][:24]
    model_selection = (
        dict(out.get("model_selection") or {})
        if isinstance(out.get("model_selection"), dict)
        else {}
    )
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
        "use_case_key": (intent_details.get("primary_use_case")
                         or (constraints.get("use_cases") or [None])[0]),
        "workloads": (intent_details.get("workload_use_cases")
                      or constraints.get("use_cases") or []),
        "workload_entities": (decision.get("workload_entities")
                              or constraints.get("workload_entities") or []),
        "workload_evidence": workload_evidence,
        "requirements": constraints.get("requirements") or {},
        "budget_min": (budget_min_cents / 100 if isinstance(budget_min_cents, (int, float))
                       else constraints.get("budget_min")),
        "budget_max": (budget_max_cents / 100 if isinstance(budget_max_cents, (int, float))
                       else constraints.get("budget_max")),
        "quantity": (constraints.get("quantity") or constraints.get("order_quantity")
                     or out.get("requested_quantity")),
        "currency": constraints.get("currency") or out.get("currency"),
        "semantic_resolution": out.get("semantic_resolution"),
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
    for item in workload_evidence.get("items") or []:
        if not isinstance(item, dict) or item.get("status") != "resolved":
            continue
        evidence_items.append({
            "type": "workload_requirement",
            "id": str(item.get("resolved_name") or item.get("requested_name") or ""),
            "source": item.get("source"),
            "source_url": item.get("source_url"),
            "retrieved_at": item.get("retrieved_at"),
            "score": 1.0,
        })

    persist_started = time.perf_counter()
    try:
        log_trace_event(
            trace_id=trace_id, event_type="recommendation_result", source_type="stage",
            source_id="Trace_Persistence", target_type="ui", target_id="right_panel",
            payload={"products_summary": summary, "right_panel_contract": right_panel,
                     "canonical_identity": canonical_identity,
                     "execution_mode": str(out.get("execution_mode") or "v2_served"),
                     "intent_analysis": intent_analysis, "constraints_used": constraints,
                     "execution_steps": execution_steps, "security": security,
                     "model_selection": model_selection,
                     "semantic_resolution": out.get("semantic_resolution"),
                     "semantic_evidence": out.get("semantic_evidence"),
                     "catalog_alignment": out.get("catalog_alignment"),
                     "case_obligations": out.get("case_obligations")},
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
                "llm": model_selection,
                "semantic_resolution": out.get("semantic_resolution"),
                "semantic_evidence": out.get("semantic_evidence"),
                "catalog_alignment": out.get("catalog_alignment"),
                "case_obligations": out.get("case_obligations"),
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
                "model_selection": model_selection,
                "semantic_resolution": out.get("semantic_resolution"),
                "semantic_evidence": out.get("semantic_evidence"),
                "catalog_alignment": out.get("catalog_alignment"),
                "case_obligations": out.get("case_obligations"),
            },
            decision_id=trace_id, tenant_id=str(tenant_id or "default"),
            actor_id=str(uid or "") or None, actor_role="buyer",
            event_type="recommendation_result",
        )
        out["_trace_recommendation_persisted"] = bool(persisted)
    except Exception as exc:
        out["_trace_recommendation_persisted"] = False
        logger.warning("core response trace persistence failed for %s: %s", trace_id, exc)
    timing["trace_persist_ms"] = round((time.perf_counter() - persist_started) * 1000.0, 1)
    projection_started = time.perf_counter()
    if products:
        try:
            from src.app.models.db import db_session
            from src.app.services.market_projection import emit_projection_events
            with db_session() as db:
                market_projections = emit_projection_events(
                    db, trace_id=trace_id, tenant_id=str(tenant_id or "default"),
                    results=products)
            if market_projections:
                out["market_projections"] = market_projections
        except Exception as exc:
            logger.warning("core market projection failed for %s: %s", trace_id, exc)
    timing["market_projection_ms"] = round(
        (time.perf_counter() - projection_started) * 1000.0, 1,
    )
    timing["finalization_ms"] = round(
        (time.perf_counter() - finalization_started) * 1000.0, 1,
    )
    out["timing_breakdown"] = timing
    try:
        log_trace_event(
            trace_id=trace_id,
            event_type="timing_breakdown",
            source_type="observer",
            source_id="Recommendation_Timing",
            target_type="trace",
            target_id=trace_id,
            payload={"timing_breakdown": timing},
        )
    except Exception as exc:
        logger.warning("core timing trace persistence failed for %s: %s", trace_id, exc)
    return out
