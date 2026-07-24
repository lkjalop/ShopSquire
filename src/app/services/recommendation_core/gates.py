"""Gates + clarify stages (V2 Phase 4, census buckets 1–2).

evaluate_text_gates(): the CORE's gate view for text turns — a real (thin) check, never
fabricated constants: injection-marker scan over the query; any scanner failure fails
CLOSED to policy_route='review' (a gate that can't run must not read as 'allow'). The full
DREAD/MITRE/vision battery stays with the platform's security services and joins the core
when the image lane lands — absent fields stay absent (structure diff shows them; MINOR).

slot_gap_clarify(): v1 clarifies on nearly every answering turn (NQE). The core's
equivalent is deterministic SLOT-GAP UX policy (not language parsing): budget missing →
ask budget; no requirements → ask use-case. One bounded question, marked clarifying.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# P1-3: the SHARED injection markers — the same source of truth the legacy commerce guard and the
# narration guard use, so no surface admits an attack string another blocks. A THIN first gate, not a
# replacement for the security battery (which joins with the image lane).
from src.app.security.injection_patterns import INJECTION_RE as _INJECTION_RE


def evaluate_text_gates(query: str) -> Dict[str, Any]:
    try:
        flagged = bool(_INJECTION_RE.search(str(query or "")))
        return {
            "policy_route": "review" if flagged else "allow",
            "image_untrusted": False,          # no image on this lane — a fact, not a default
            "injection_flagged": flagged,
        }
    except Exception:
        return {"policy_route": "review", "image_untrusted": False, "injection_flagged": None}


def slot_gap_clarify(*, has_products: bool, budget_known: bool,
                     has_requirements: bool, has_use_case: bool = False) -> Optional[Dict[str, Any]]:
    if not has_products:
        # Empty retrieval is when a clarify matters MOST, not least: a missing slot on a zero-result
        # turn is a recoverable dead-end, so ask ONE narrowing question instead of returning nothing.
        # A fully-specified empty turn stays None (an honest no-match, not a slot gap).
        if not budget_known:
            return {"id": "ask_budget_empty", "goal": "recover_empty", "reason": "empty_budget_slot",
                    "text": "I didn't find a match yet — what budget range should I stay within so I can look again?"}
        if not has_requirements and not has_use_case:
            return {"id": "ask_use_case_empty", "goal": "recover_empty", "reason": "empty_use_case_slot",
                    "text": "I didn't find a match yet — what will you mainly use it for? That changes which specs matter."}
        return None
    if not budget_known:
        return {"id": "ask_budget", "text": "What budget range should I stay within?",
                "goal": "narrow_results", "reason": "budget_slot_empty"}
    if not has_requirements and not has_use_case:
        return {"id": "ask_use_case", "text": "What will you mainly use it for? That "
                "changes which specs matter.", "goal": "narrow_results",
                "reason": "use_case_slot_empty"}
    return None


def material_pre_retrieval_clarify(*, quantity: Optional[int], budget_known: bool,
                                   budget_scope: str) -> Optional[Dict[str, Any]]:
    """Stop before retrieval only when an unresolved slot changes authorization semantics.

    A missing generic use case does not qualify: balanced retrieval can proceed and refine later.
    Whole-order versus per-unit budget does qualify because retrieval would apply different price
    ceilings and could present a mathematically invalid slate.
    """
    if quantity is not None and quantity >= 2 and budget_known and budget_scope == "unknown":
        return {
            "id": "budget_scope",
            "goal": "resolve_budget_scope",
            "reason": "missing_material_budget_scope",
            "missing_slots": ["budget_scope"],
            "text": f"Is that budget per item, or the total for all {quantity}?",
            "options": [
                {"id": "per_unit", "label": "Per item"},
                {"id": "total", "label": f"Total for all {quantity}"},
            ],
        }
    return None
