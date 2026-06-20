"""Buyer persona detection + persona-calibrated LLM prompt context.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
CORE (vertical-agnostic):
  • detect_buyer_persona() / detect_buyer_persona_with_confidence() — the matching
    ALGORITHM (iterate patterns, score, return best).  Works for any vertical.
  • build_persona_prompt_context() — the DISPATCH mechanism (look up persona→prompt).

ADAPTER (product-type-specific, currently hardcoded electronics):
  • PERSONA_PATTERNS — the keywords are electronics/laptop-centric (ray tracing,
    CUDA, refresh rate, gaming titles). A pharmacy vertical would have different
    persona patterns (pharmacist, patient, caregiver, aged-care).
  • The prompt strings in build_persona_prompt_context() — every block references
    laptop specs (RAM, GPU VRAM, battery, display inches). Pharmacy/fashion would
    have entirely different emphasis guidance.

MIGRATION PATH (Phase 2):
  Add `persona_patterns` and `persona_prompt_templates` slots to StoreProfile.
  The CORE algorithm stays; the ADAPTER data moves to config/store_profiles/*.json.
  Transitional: inline electronics data retained as fallback when profile lacks slots.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER DATA — persona detection patterns, resolved PER REQUEST from the active
# StoreProfile's `persona_patterns` slot (Phase 2A P0: the electronics patterns moved
# VERBATIM to config/store_profiles/electronics.json; fashion/pharmacy define their own,
# so a non-electronics vertical detects ITS personas, never electronics ones).
# The detection ALGORITHM below stays CORE (vertical-blind).
# ═══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=8)
def _persona_patterns_for(pid: str) -> dict[str, list[str]]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("persona_patterns", profile_id=pid, default=None)
    return {k: list(v) for k, v in raw.items()} if isinstance(raw, dict) and raw else {}


def _active_persona_patterns() -> dict[str, list[str]]:
    from src.app.platform.store_profile import active_profile_id
    return _persona_patterns_for(active_profile_id())


@lru_cache(maxsize=8)
def _persona_prompt_templates_for(pid: str) -> list:
    """Ordered first-match persona-prompt rules from the active StoreProfile (Phase 2A P1)."""
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("persona_prompt_templates", profile_id=pid, default=None)
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _active_persona_prompt_templates() -> list:
    from src.app.platform.store_profile import active_profile_id
    return _persona_prompt_templates_for(active_profile_id())


def reset_cache() -> None:
    """Clear the per-profile persona caches (test isolation / profile reload)."""
    for fn in (_persona_patterns_for, _persona_prompt_templates_for):
        try:
            fn.cache_clear()
        except Exception:
            pass


# Back-compat module constant (electronics default) for direct importers (recommend.py
# aliases it). Runtime detection uses the per-request accessor via the functions below.
PERSONA_PATTERNS: dict[str, list[str]] = _persona_patterns_for("electronics")


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Persona detection algorithm (vertical-agnostic).
# Works against ANY set of patterns; the pattern dict is the adapter input.
# ═══════════════════════════════════════════════════════════════════════════════

def detect_buyer_persona(query: str | None) -> str | None:
    """Classify the buyer persona from query text. Returns the best-match persona or None."""
    q = str(query or "").lower()
    if not q:
        return None
    best, best_score = None, 0
    for persona, patterns in _active_persona_patterns().items():
        score = sum(1 for p in patterns if re.search(p, q, re.IGNORECASE))
        if score > best_score:
            best_score = score
            best = persona
    return best if best_score > 0 else None


def detect_buyer_persona_with_confidence(query: str | None) -> Tuple[str | None, float, Dict[str, int]]:
    q = str(query or "").lower()
    if not q:
        return None, 0.0, {}
    scores: Dict[str, int] = {}
    best: str | None = None
    best_score = 0
    for persona, patterns in _active_persona_patterns().items():
        score = sum(1 for p in patterns if re.search(p, q, re.IGNORECASE))
        if score > 0:
            scores[persona] = score
        if score > best_score:
            best_score = score
            best = persona
    if not best:
        return None, 0.0, scores
    conf = max(0.0, min(1.0, float(best_score) / 2.0))
    return best, conf, scores


# ═══════════════════════════════════════════════════════════════════════════════
# CORE DISPATCH — persona-calibrated prompt blocks.
# The CONTENT (ADAPTER) lives in StoreProfile["persona_prompt_templates"] as ordered
# first-match rules (Phase 2A P1). The electronics rules were excised VERBATIM to
# electronics.json; a vertical that defines no templates returns None (generic prompt),
# never an electronics block.
# ═══════════════════════════════════════════════════════════════════════════════

def build_persona_prompt_context(
    use_case: str,
    buyer_persona: str,
    budget_bracket: str | None,
) -> str | None:
    """Return a persona-calibrated context block injected into the LLM prompt.

    Maps use_case + buyer_persona to: who the shopper is, which specs matter
    in plain English, and tone guidance.  Returns None for unknown personas.
    """
    uc = (use_case or "").lower().strip()
    bp = (buyer_persona or "").lower().strip()
    br = (budget_bracket or "").lower().strip()

    # Profile-driven (vertical-agnostic) first-match dispatch. The ADAPTER content lives in
    # StoreProfile["persona_prompt_templates"] (electronics excised verbatim); a vertical with
    # no templates returns None (generic prompt) — never an electronics block.
    for _rule in _active_persona_prompt_templates():
        _personas = _rule.get("personas") or []
        _use_cases = _rule.get("use_cases") or []
        _contains = _rule.get("use_cases_contains") or []
        if (bp and bp in _personas) or (uc and uc in _use_cases) or any(s in uc for s in _contains):
            return _rule.get("text")
    return None
