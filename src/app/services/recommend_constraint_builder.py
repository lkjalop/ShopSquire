"""Constraint assembly — builds the initial constraints dict from NLP + budget + memory.

Extracted from recommend.py Phase 2 (F1 Constraint Engine). This is the pure-function
core that assembles the constraints dict from heterogeneous sources:
  - Request parameters (budget_min/max)
  - NLP analysis output (preferences, intent, slots)
  - Decayed user preferences from memory (kv)
  - Confirmed slots from structured_state
  - Query decomposition (parsed budget/brands/specs)

The function is deterministic: same inputs → same output. No I/O, no side effects.
Vertical-blind (no product-type assumptions).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from src.app.deps import scrub_pii


def build_initial_constraints(
    *,
    uid_hash: str,
    query: str,
    budget_min: Optional[int],
    budget_max: Optional[int],
    nlp: Dict[str, Any],
    parsed: Dict[str, Any],
    confirmed_slots: Dict[str, Any],
    decayed_pref_fn: Callable[..., Any],
    shortlist_lock_active: bool,
    turn_intent: str,
    locale: Optional[str],
) -> Dict[str, Any]:
    """Assemble the canonical constraints dict from all input sources.

    Priority order for each slot: request param > NLP parse > decayed memory > confirmed slots.
    Returns a new dict; does NOT mutate any inputs.
    """
    prefs = nlp.get("preferences") or {}

    return {
        "uid_hash": uid_hash,
        "budget_max": (
            budget_max
            or parsed.get("budget_max")
            or prefs.get("budget_max")
            or decayed_pref_fn("budget_max")
            or confirmed_slots.get("budget_max")
        ),
        "budget_min": (
            budget_min
            or parsed.get("budget_min")
            or prefs.get("budget_min")
            or decayed_pref_fn("budget_min")
            or confirmed_slots.get("budget_min")
        ),
        "brands": (
            parsed.get("brands")
            or prefs.get("brands")
            or decayed_pref_fn("brands", [])
            or confirmed_slots.get("brands")
            or []
        ),
        "specs": (
            parsed.get("specs")
            or prefs.get("specs")
            or decayed_pref_fn("specs", [])
            or confirmed_slots.get("specs")
            or []
        ),
        "brand_excludes": (
            parsed.get("brand_excludes")
            or prefs.get("brand_excludes")
            or decayed_pref_fn("brand_excludes", [])
            or confirmed_slots.get("brand_excludes")
            or []
        ),
        "availability": (
            parsed.get("availability")
            or prefs.get("availability")
            or decayed_pref_fn("availability")
            or confirmed_slots.get("availability")
        ),
        "condition": (
            parsed.get("condition")
            or prefs.get("condition")
            or decayed_pref_fn("condition")
            or confirmed_slots.get("condition")
        ),
        "intent": nlp.get("intent"),
        "use_case": prefs.get("use_case") or decayed_pref_fn("use_case") or confirmed_slots.get("use_case"),
        "use_case_tags": prefs.get("use_case_tags") or decayed_pref_fn("use_case_tags", []) or confirmed_slots.get("use_case_tags") or [],
        "locale": locale,
        "query": scrub_pii(query or ""),
        "slots": nlp.get("slots") or {},
        "shortlist_lock_active": shortlist_lock_active,
        "turn_intent": turn_intent,
        "_request_budget_max": budget_max,
        "_request_budget_min": budget_min,
    }


def enrich_constraints_with_persona(
    constraints: Dict[str, Any],
    *,
    buyer_persona: Optional[str],
    buyer_persona_confidence: float,
    persona_scores: Optional[Dict[str, int]],
    persona_min_confidence: float = 0.34,
) -> None:
    """Mutate constraints in-place with buyer persona detection results."""
    if buyer_persona and buyer_persona_confidence >= persona_min_confidence:
        constraints["buyer_persona"] = buyer_persona
        constraints["buyer_persona_confidence"] = round(float(buyer_persona_confidence), 4)
    elif buyer_persona:
        constraints["buyer_persona_candidate"] = buyer_persona
        constraints["buyer_persona_confidence"] = round(float(buyer_persona_confidence), 4)
        constraints["buyer_persona_low_confidence"] = True
    if persona_scores:
        constraints["buyer_persona_scores"] = persona_scores


def merge_accumulated_slots(
    constraints: Dict[str, Any],
    accumulated: Dict[str, Any],
) -> None:
    """Merge NQE-answered fields from prior turns into constraints (in-place).

    Only fills slots that are currently empty — never overwrites explicit user input.
    """
    if not accumulated or not isinstance(accumulated, dict):
        return
    if not constraints.get("budget_min") and accumulated.get("budget_min"):
        constraints["budget_min"] = accumulated["budget_min"]
    if not constraints.get("budget_max") and accumulated.get("budget_max"):
        constraints["budget_max"] = accumulated["budget_max"]
    if not constraints.get("use_case") and accumulated.get("use_case"):
        constraints["use_case"] = accumulated["use_case"]
    if not constraints.get("use_case_tags") and accumulated.get("use_case_tags"):
        constraints["use_case_tags"] = accumulated["use_case_tags"]
    if accumulated.get("gpu_preference") and not constraints.get("gpu_preference"):
        constraints["gpu_preference"] = accumulated["gpu_preference"]


def merge_confirmed_slots(
    constraints: Dict[str, Any],
    confirmed: Dict[str, Any],
) -> None:
    """Merge confirmed (turn-end contract) slots into constraints (in-place).

    Only fills slots that are currently empty.
    """
    if not confirmed or not isinstance(confirmed, dict):
        return
    if constraints.get("budget_min") is None and confirmed.get("budget_min") is not None:
        constraints["budget_min"] = confirmed["budget_min"]
    if constraints.get("budget_max") is None and confirmed.get("budget_max") is not None:
        constraints["budget_max"] = confirmed["budget_max"]
    if not constraints.get("use_case") and confirmed.get("use_case"):
        constraints["use_case"] = confirmed["use_case"]
    if not (constraints.get("brands") or []) and isinstance(confirmed.get("brands"), list):
        constraints["brands"] = list(confirmed["brands"])[:8]
    if not (constraints.get("specs") or []) and isinstance(confirmed.get("specs"), list):
        constraints["specs"] = list(confirmed["specs"])[:12]
    if not constraints.get("availability") and confirmed.get("availability"):
        constraints["availability"] = confirmed["availability"]
    if not constraints.get("condition") and confirmed.get("condition"):
        constraints["condition"] = confirmed["condition"]
