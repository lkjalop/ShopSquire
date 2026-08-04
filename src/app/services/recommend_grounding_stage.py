"""Grounding-ladder stage (extracted from suggest()) — anti-hallucination identity grounding.

Asserts product identity only to the level the catalog can confirm: a VLM/OCR-guessed brand the catalog
can't fulfil is DROPPED (not asserted), and the residual lowers identity confidence so the NQE clarifying
question fires. Behaviour-preserving extraction:
  * no-ops (returns inputs unchanged) when there is no image payload or the env gate is off;
  * no-ops when id_result is absent — the inline block relied on a NameError→except to skip that case, so
    the caller passes locals().get("_id_result") and this stage treats None as "skip" (identical effect);
  * mutates ``constraints`` IN PLACE (brand drop + grounded-tier annotations) and returns the possibly
    updated (image_identity_confidence, strict_image_brand_hint).

Dependencies injected (trace logger); the grounding_ladder service is imported lazily. Vertical-blind.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple


def run_grounding_ladder(
    *,
    query: Any,
    constraints: Dict[str, Any],
    incoming_image_payload: Any,
    id_source: Any,
    id_result: Any,
    image_blob: Any,
    image_identity_confidence: float,
    strict_image_brand_hint: Any,
    db: Any,
    trace_id: Any,
    trace_fn: Callable[..., Any],
    enabled: bool = True,
) -> Tuple[float, Any]:
    """Run the grounding ladder; return (image_identity_confidence, strict_image_brand_hint). Never raises
    (a grounding failure is recorded against the trace, then continues)."""
    if not (incoming_image_payload and enabled):
        return image_identity_confidence, strict_image_brand_hint
    try:
        if id_result is None:
            # the inline block referenced _id_result directly; when it was undefined the NameError fell
            # to the except and grounding was skipped. None here reproduces that skip exactly.
            return image_identity_confidence, strict_image_brand_hint
        from src.app.services.grounding_ladder import get_catalog_brands, resolve_grounded_identity
        _gl_src = str(id_source or "")
        _grounded = resolve_grounded_identity(
            query=query,
            text_identity=id_result if _gl_src == "text_heuristic" else None,
            vision_identity=id_result if _gl_src in ("vision_image", "vision_brand_rescue") else None,
            image_bytes=image_blob,
            catalog_brands=get_catalog_brands(db),
            budget_max=float(constraints.get("budget_max")) if constraints.get("budget_max") else None,
            trace_id=trace_id,
        )
        # Grounding gate: drop an ungrounded/conflicted brand rather than assert it.
        if constraints.get("brand") and not _grounded.brand:
            _dropped = constraints.pop("brand", None)
            constraints.pop("_request_brand_hint", None)
            if isinstance(constraints.get("brands"), list):
                _kept = [b for b in constraints["brands"]
                         if str(b).strip().lower() != str(_dropped).strip().lower()]
                constraints["brands"] = _kept or None
                if not constraints["brands"]:
                    constraints.pop("brands", None)
            strict_image_brand_hint = None
            trace_fn(
                trace_id, "grounding_ladder_brand_dropped", "agent", "Product_Identity_Agent",
                "system", None, {"dropped_brand": _dropped, "tier": _grounded.tier_name,
                                 "reason": "ungrounded_or_conflict"},
            )
        # Identity confidence now reflects the grounded tier (drives NQE residual).
        image_identity_confidence = float(_grounded.confidence)
        constraints["_grounded_tier"] = _grounded.tier_name
        constraints["_identity_confidence_label"] = _grounded.confidence_label
        if _grounded.residual_question:
            constraints["_identity_residual_question"] = _grounded.residual_question
        trace_fn(trace_id, "grounding_ladder", "agent", "Product_Identity_Agent", "system", None,
                 _grounded.to_dict())
    except Exception as _gl_exc:
        # P1: never swallow a grounding failure silently — it degrades brand grounding invisibly.
        trace_fn(
            trace_id, "stage_partial_failure", "system", "image_grounding", "system", None,
            {"stage": "image_grounding", "error": f"{type(_gl_exc).__name__}: {_gl_exc}",
             "severity": "warn", "degraded": True},
        )
    return image_identity_confidence, strict_image_brand_hint
