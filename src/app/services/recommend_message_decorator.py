"""
═══════════════════════════════════════════════════════════════════════════
recommend_message_decorator — CORE (vertical-agnostic)
═══════════════════════════════════════════════════════════════════════════
Assistant message decoration chain for the recommend pipeline.

Applies budget advice, availability lines, constraint honesty prefixes,
comparative synthesis, and price range notes to the assistant message.
These are pure text transforms — they read constraints/results and return
an augmented message string. No DB or Redis access, no side-effects.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


def apply_budget_advice(
    assistant_message: Optional[str],
    constraints: Dict[str, Any],
    payload: Dict[str, Any],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Append budget fitness advice and populate alternatives on low budget.

    Returns (updated_message, updated_payload).
    """
    try:
        bf = constraints.get("budget_fitness") if isinstance(constraints.get("budget_fitness"), dict) else {}
        status = str(bf.get("status") or "").strip().lower()
        advice = str(bf.get("advice") or "").strip()
        if status in {"low", "high"} and advice:
            assistant_message = f"{assistant_message} {advice}" if assistant_message else advice
        if status == "low":
            alts = payload.get("alternatives") if isinstance(payload.get("alternatives"), list) else []
            floor = int(float(bf.get("floor") or 0)) if bf.get("floor") is not None else 0
            if floor > 0:
                alts.append(f"Raise budget to around ${floor:,} for this use-case")
            alts.append("Keep budget and prioritize refurbished / previous generation")
            alts.append("Relax one or two strict specs to widen options")
            payload["alternatives"] = list(dict.fromkeys([str(x) for x in alts if str(x).strip()]))[:4]
    except Exception:
        pass
    return assistant_message, payload


def apply_contextual_notes(
    assistant_message: Optional[str],
    *,
    image_brand_mismatch_note: Optional[str],
    brand_budget_answer: Any,
    gpu_inference_note: Optional[str],
    availability_line: Optional[str],
) -> Optional[str]:
    """Append contextual notes (image mismatch, GPU inference, availability)."""
    if image_brand_mismatch_note and not brand_budget_answer:
        assistant_message = (
            f"{assistant_message} {image_brand_mismatch_note}"
            if assistant_message
            else image_brand_mismatch_note
        )
    if gpu_inference_note:
        assistant_message = (
            f"{assistant_message} {gpu_inference_note}"
            if assistant_message
            else gpu_inference_note
        )
    if availability_line:
        assistant_message = (
            f"{assistant_message} {availability_line}".strip()
            if assistant_message
            else availability_line
        )
    return assistant_message


def apply_constraint_honesty_prefix(
    assistant_message: Optional[str],
    constraints: Dict[str, Any],
) -> Optional[str]:
    """Prepend relaxation note when constraint match is inexact."""
    cstatus = (
        constraints.get("constraint_status")
        if isinstance(constraints.get("constraint_status"), dict)
        else {}
    )
    if cstatus.get("exact_match") is False and cstatus.get("relaxation_note"):
        rn = str(cstatus["relaxation_note"])
        assistant_message = f"{rn} {assistant_message}".strip() if assistant_message else rn
    return assistant_message


def build_comparative_synthesis(
    query: Optional[str],
    results: List[Dict[str, Any]],
    humanize_fn: Callable[[List], List[str]],
) -> Optional[str]:
    """Build a ranked comparison message for "which is better" queries.

    Returns the synthesis message if applicable, else None.
    """
    try:
        needs_synthesis = any(
            phrase in (query or "").lower()
            for phrase in [
                "which is better",
                "which one should",
                "what do you recommend",
                "pros and cons",
                "which would you",
                "best choice",
            ]
        )
        if not needs_synthesis or not results:
            return None
        top = results[:3]
        lines = []
        for i, r in enumerate(top):
            pros = (r.get("factors") or {}).get("positive", [])
            price = (
                int(r.get("price_cents") or 0) // 100
                if r.get("price_cents") is not None
                else r.get("price")
            )
            pros_h = humanize_fn(pros)
            why = (" - " + "; ".join(pros_h)) if pros_h else ""
            lines.append(f"{i+1}. {r.get('name')} (${price}){why}")
        return (
            "Based on your criteria and our current inventory:\n\n"
            + "\n".join(lines)
            + "\n\nThese rankings consider price match, spec relevance, and stock availability. "
            "Ask for more detail on any item if you'd like."
        )
    except Exception:
        return None


def apply_price_range_note(
    assistant_message: Optional[str],
    payload: Dict[str, Any],
) -> Optional[str]:
    """Append a price range summary note when 2+ results exist."""
    try:
        pr_range = payload.get("price_range")
        if pr_range and pr_range.get("count", 0) >= 2:
            pr_min = pr_range["min"]
            pr_max = pr_range["max"]
            pr_median = pr_range["median"]
            note = (
                f"\n\n💰 Price range: ${pr_min:,.0f} – ${pr_max:,.0f} "
                f"(median ${pr_median:,.0f}) across {pr_range['count']} results."
            )
            assistant_message = (assistant_message or "") + note
    except Exception:
        pass
    return assistant_message
