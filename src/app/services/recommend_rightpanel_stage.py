"""Right-panel assembly stage for the recommendation route (extracted from suggest()).

Builds the storefront ``right_panel`` contract — the SUPPORT-claim panel (warranty / repair / escalation
cards + FAQ playbooks) or the SHOPPING panel (budget status + tier split) — applies the image-security
response fields, and logs the recommendation_result UI trace event. Behaviour-preserving: the whole body
is under one ``try/except: pass`` (exactly as inline), and the stage returns the CURRENT
(payload, results, assistant_message) so partial mutations before any failure persist identically.

All route-local dependencies are injected (the image-security helper, the warranty lookup, the trace
logger) so this stays unit-testable with no app wiring. Vertical-blind.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple


def assemble_right_panel(
    payload: Dict[str, Any],
    *,
    results: Any,
    assistant_message: Any,
    analysis: Dict[str, Any],
    severity: Any,
    image_reupload_reasons: Any,
    image_cv_signals_parsed: Any,
    turn_intent: Any,
    constraints: Dict[str, Any],
    uid: Any,
    decision_id: Any,
    trace_id: Any,
    nlp: Any,
    apply_image_security_fields: Callable[..., Dict[str, Any]],
    infer_warranty: Callable[[Any], Dict[str, Any]],
    trace_fn: Callable[..., Any],
) -> Tuple[Dict[str, Any], Any, Any]:
    """Assemble payload['right_panel'] (+ image-security fields + the UI trace event). Returns the current
    (payload, results, assistant_message) — payload is also mutated in place. Never raises."""
    try:
        payload = apply_image_security_fields(
            payload,
            analysis_details=analysis.get("details") or {},
            severity=severity,
            image_reupload_reasons=image_reupload_reasons,
            image_cv_signals_parsed=image_cv_signals_parsed,
        )
        _image_untrusted = bool(image_reupload_reasons)
        _security_route = "visual_sanitized" if _image_untrusted else "allow"
        _security_summary = (
            "Image flagged; using text-only fallback until a clean product photo is uploaded."
            if _image_untrusted
            else None
        )
        if str(turn_intent or "").upper() == "SUPPORT_CLAIM":
            _issue = str(constraints.get("issue_type") or "device_issue").strip().lower() or "device_issue"
            _warranty = infer_warranty(uid)
            results = []
            payload["results"] = []
            assistant_message = (
                "This looks like a damaged device. I can help with repair, warranty, or return steps. "
                + (
                    "I found account order history to review next."
                    if str(_warranty.get("status") or "").strip().lower() == "found"
                    else "Upload a receipt or order reference if you have one."
                )
            )
            payload["right_panel"] = {
                "mode": "support",
                "show_tiers": False,
                "summary": f"Support flow active for {(_issue or 'device issue').replace('_', ' ')}.",
                "image_untrusted": _image_untrusted,
                "image_degraded_mode": _image_untrusted,
                "security_route": _security_route,
                "security_summary": _security_summary,
                "support_cards": [
                    {
                        "id": "warranty_status",
                        "title": "Warranty/Coverage",
                        "status": _warranty.get("status") or "unknown",
                        "message": _warranty.get("message") or "Sign in and provide order details to verify coverage.",
                        "order_ref": _warranty.get("order_ref"),
                    },
                    {
                        "id": "repair_return",
                        "title": "Repair / Return Path",
                        "status": "review",
                        "message": "Upload clear device and receipt photos to determine repair, return, or in-store diagnostics.",
                    },
                    {
                        "id": "escalation",
                        "title": "Escalation",
                        "status": "available",
                        "message": "Escalate to human support if automated checks remain inconclusive.",
                    },
                ],
                "faq_playbooks": [
                    {
                        "id": "faq_bsod",
                        "title": "Blue Screen quick checks",
                        "steps": ["Boot safe mode", "Rollback latest drivers", "Collect Event Viewer logs"],
                    },
                    {
                        "id": "faq_cracked_screen",
                        "title": "Physical damage claims",
                        "steps": ["Capture damage close-up", "Capture serial/label", "Attach receipt or order reference"],
                    },
                ],
                "parallel_agents": [
                    "CV_Triage_Agent",
                    "OCR_QR_Agent",
                    "Device_Match_Agent",
                    "Warranty_Agent",
                    "Support_Playbook_Agent",
                    "Security_Observer_Agent",
                ],
            }
        else:
            _rt = payload.get("recommendation_tiers") if isinstance(payload.get("recommendation_tiers"), dict) else {}
            payload["right_panel"] = {
                "mode": "shopping",
                "show_tiers": bool(_rt.get("show_split")),
                "budget_status": str((payload.get("budget_viability") or {}).get("status") or "unknown"),
                "image_untrusted": _image_untrusted,
                "image_degraded_mode": _image_untrusted,
                "security_route": _security_route,
                "security_summary": _security_summary,
                "lower_tier": {
                    "title": "Minimum / budget-fit",
                    "items": (_rt.get("minimum") or [])[:4],
                    "explanation": _rt.get("minimum_explanation"),
                },
                "higher_tier": {
                    "title": "Recommended / performance-fit",
                    "items": (_rt.get("recommended") or [])[:4],
                    "explanation": _rt.get("recommended_explanation"),
                },
            }
        _trace_for_ui_event = decision_id or trace_id
        if _trace_for_ui_event:
            try:
                _safe_right_panel = json.loads(json.dumps(payload.get("right_panel"), ensure_ascii=False, default=str))
            except Exception:
                _safe_right_panel = {"mode": str((payload.get("right_panel") or {}).get("mode") or "")}
            trace_fn(
                trace_id=_trace_for_ui_event,
                event_type="recommendation_result",
                source_type="agent",
                source_id="Product_Ranking_Agent",
                target_type="ui",
                target_id="right_panel",
                payload={
                    "products_summary": [
                        {
                            "sku": str(p.get("sku") or ""),
                            "name": str(p.get("name") or ""),
                            "score_norm": float(p.get("score_norm")) if isinstance(p.get("score_norm"), (int, float)) else p.get("score_norm"),
                            "reasons": [str(x) for x in ((p.get("reasons") or (p.get("factors") or {}).get("positive") or [])[:3])],
                            "reason_codes": (p.get("reason_codes") or [])[:3],
                            "price": float(p.get("price")) if isinstance(p.get("price"), (int, float)) else p.get("price"),
                        }
                        for p in (results or [])[:8]
                        if isinstance(p, dict)
                    ],
                    "right_panel_contract": _safe_right_panel,
                    "intent_snapshot": {
                        "persona": constraints.get("buyer_persona"),
                        "use_case_key": (payload.get("use_case_analysis") or {}).get("use_case_key"),
                        "budget_min": constraints.get("budget_min"),
                        "budget_max": constraints.get("budget_max"),
                        "intent": (nlp or {}).get("intent"),
                        "source": "recommend.final_payload",
                    },
                },
            )
    except Exception:
        pass
    return payload, results, assistant_message
