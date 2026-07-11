"""Legacy response adapter (V2 Phase 4, step 1) — the ONLY place the recorded /suggest
contract forks exist.

Phase 0 proved /suggest returns four distinct top-level shapes. The adjudicated decision
(status doc §7 Q1, GPT-5.6 concurring): unify INTERNALLY (CoreResponse), emulate the forks
HERE until chat/frontend migrate to the unified envelope — then this file is deleted whole.

Emulation is measured against the frozen contract, not vibes:
  • full_pipeline output must carry every CORE_FIELD and pass validate_response with ZERO
    violations (v1's own clarify branches couldn't say that — the adapter is stricter than
    the thing it emulates).
  • recommend_parity_full.message_class must classify adapter output identically to how it
    classifies the corpus recording of the same outcome — otherwise shadow diffs would
    measure the ADAPTER, not the core.
Fields the core genuinely doesn't produce yet (persona, complexity, narration jobs …) get
HONEST inert defaults — never fabricated values that could be mistaken for signals.
"""
from __future__ import annotations

from typing import Any, Dict

from src.app.services.recommendation_core.envelope import CoreResponse

SHAPES = ("full_pipeline", "inventory_fast", "claims", "policy_faq")


def to_legacy(core: CoreResponse, *, shape: str = "full_pipeline") -> Dict[str, Any]:
    core = core.finalize()
    if shape == "inventory_fast":
        return _inventory_fast(core)
    if shape == "claims":
        return _claims(core)
    if shape == "policy_faq":
        return _policy_faq(core)
    return _full_pipeline(core)


def _universal(core: CoreResponse) -> Dict[str, Any]:
    """The 4 fields present on EVERY recorded branch — the true contract invariant."""
    return {
        "trace_id": core.envelope.trace_id,
        "decision_id": core.decision_id,
        "decision_trace_id": core.envelope.trace_id,
        "_trace_recommendation_persisted": True,
    }


def _full_pipeline(core: CoreResponse) -> Dict[str, Any]:
    products = [p.as_dict() for p in core.products]
    clarifying = bool(core.clarify)
    payload: Dict[str, Any] = {
        **_universal(core),
        # ── the outcome (real core output) ────────────────────────────────────
        "assistant_message": core.message,
        "message": core.message,          # branch-duplicate field, kept for consumers
        "products": products,
        "results": products,              # recorded duplication — preserved at the edge
        "off_catalog": core.off_catalog,
        "refusal_note": core.refusal_note,
        "degraded": core.degraded,
        "needs_disambiguation": clarifying,
        "next_questions": core.clarify,
        "workload_fit": core.fit_summary,
        # v1 semantics: a budget-carrying search reads as FILTER (the recorded naming)
        "turn_intent": ("FILTER" if core.lane == "SEARCH"
                        and (core.envelope.budget_max_cents is not None
                             or core.envelope.budget_min_cents is not None)
                        else core.lane),
        "turn_type": f"{core.lane.lower()}_turn",
        "security": {"policy_route": (core.extras.get("gates") or {}).get("policy_route"),
                     "image_untrusted": (core.extras.get("gates") or {}).get("image_untrusted")},
        "autonomy_tier": "caution",   # the platform-wide default posture; levers stay gated
        "escalation": core.extras.get("escalation"),
        "grounding_status": core.grounding,   # contract ADDITION (visible in KNOWN_FIELDS review)
        # ── legacy-required CORE_FIELDS the core doesn't produce yet: HONEST inert
        # defaults, populated stage-by-stage as Phase 4 proceeds — never fabricated ──
        "agent_chain": core.extras.get("agent_chain", []),
        "ambiguity_reason": core.extras.get("ambiguity_reason"),
        "buyer_persona": None, "buyer_persona_candidate": None, "buyer_persona_confidence": None,
        "complexity_signals": core.extras.get("complexity_signals", {}),
        "confidence_band": core.extras.get("confidence_band", "unscored"),
        "confidence_calibrated": None,
        "constraints_used": core.extras.get("constraints_used", {}),
        "counterfactual": None,
        "eligible": True,
        "evidence_items": core.extras.get("evidence_items", []),
        "evidence_weighting": {},
        "followup_contract": {},
        "intent_execution_plan": core.extras.get("plan", {}),
        "llm_model": core.extras.get("llm_model", "recommendation_core"),
        "memory_confidence": None,
        "model_tier": core.extras.get("model_tier", "core"),
        "policy_version": "v1",
        "proposal": {"decision_mode": "recommendation_core",
                     "ranked_skus": [p.sku for p in core.products]},
        "question_plan": {"mode": "clarify" if clarifying else "none"},
        "referents": {"has_reference": False, "skus": [], "source": None},
        "view_mode": "grid",
        "view_reason": "recommendation_core",
    }
    return payload


def _inventory_fast(core: CoreResponse) -> Dict[str, Any]:
    return {
        **_universal(core),
        "answer": core.message,
        "recommendations": [p.as_dict() for p in core.products],
        "inventory": core.extras.get("inventory", {}),
        "nqe": {"questions": core.clarify},
        "source": "recommendation_core",
        "timing": core.extras.get("timing", {}),
        "injection_blocked": False,
    }


def _claims(core: CoreResponse) -> Dict[str, Any]:
    return {
        **_universal(core),
        "assistant_message": core.message,
        "status": core.extras.get("claim_status", "received"),
        "incident_id": core.extras.get("incident_id"),
        "needs_human_review": bool(core.extras.get("needs_human_review", True)),
        "human_review": core.extras.get("human_review"),
        "buyer_token": core.extras.get("buyer_token"),
    }


def _policy_faq(core: CoreResponse) -> Dict[str, Any]:
    return {
        **_universal(core),
        "assistant_message": core.message,
        "message": core.message,
        "status": "answered",
        "availability": core.extras.get("availability"),
        "fulfillment_options": core.extras.get("fulfillment_options"),
    }
