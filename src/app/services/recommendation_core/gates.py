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

# the same marker families the platform's injection scanners key on — a THIN first gate,
# not a replacement for the security battery (which joins with the image lane)
_INJECTION_RE = re.compile(
    r"ignore (all|previous|prior) (instructions|rules)|system prompt|<\s*script|"
    r"you are now|jailbreak|do anything now", re.IGNORECASE)


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
                     has_requirements: bool) -> Optional[Dict[str, Any]]:
    if not has_products:
        return None
    if not budget_known:
        return {"id": "ask_budget", "text": "What budget range should I stay within?",
                "goal": "narrow_results", "reason": "budget_slot_empty"}
    if not has_requirements:
        return {"id": "ask_use_case", "text": "What will you mainly use it for? That "
                "changes which specs matter.", "goal": "narrow_results",
                "reason": "use_case_slot_empty"}
    return None
