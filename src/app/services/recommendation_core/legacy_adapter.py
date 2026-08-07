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

import time
from typing import Any, Dict, Optional

from src.app.services.recommendation_core.envelope import CoreResponse
from src.app.services.recommendation_core.trace_ontology import build_execution_steps

SHAPES = ("full_pipeline", "inventory_fast", "claims", "policy_faq")


def to_legacy(core: CoreResponse, *, shape: str = "full_pipeline") -> Dict[str, Any]:
    started = time.perf_counter()
    core = core.finalize()
    if shape == "inventory_fast":
        payload = _inventory_fast(core)
    elif shape == "claims":
        payload = _claims(core)
    elif shape == "policy_faq":
        payload = _policy_faq(core)
    else:
        payload = _full_pipeline(core)
    timing = dict(payload.get("timing_breakdown") or core.extras.get("timing_breakdown") or {})
    timing["response_shape_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    payload["timing_breakdown"] = timing
    return payload


def _universal(core: CoreResponse) -> Dict[str, Any]:
    """The 4 fields present on EVERY recorded branch — the true contract invariant."""
    return {
        "trace_id": core.envelope.trace_id,
        "decision_id": core.decision_id,
        "decision_trace_id": core.envelope.trace_id,
        # GPT-5.6 blocking finding #2: this was True — a FABRICATED audit signal that made
        # _with_trace() SKIP real persistence. False is the truth: the core does not persist
        # its own trace yet; the caller's persistence block must run. Flips to True only
        # when the facade owns persistence and actually did it.
        "_trace_recommendation_persisted": False,
    }


def _workload_fit(core: CoreResponse) -> Optional[Dict[str, Any]]:
    fit = dict(core.fit_summary or {})
    if fit.get("requirements") and not fit.get("floors"):
        fit["floors"] = fit["requirements"]
    if core.products and not fit.get("verdicts"):
        fit["verdicts"] = [
            {"sku": card.sku, **dict(card.fit or {})}
            for card in core.products if card.fit
        ]
    return fit or None


def _full_pipeline(core: CoreResponse) -> Dict[str, Any]:
    products = [p.as_dict() for p in core.products]
    clarifying = bool(core.clarify)
    subject_action = str((core.extras.get("decision") or {}).get("subject_action") or "")
    constraints_used = dict(core.extras.get("constraints_used") or {})
    constraints_used.setdefault("currency", core.envelope.currency)
    decision = dict(core.extras.get("decision") or {})
    route_stage = next(
        (
            stage for stage in (core.extras.get("stage_results") or [])
            if isinstance(stage, dict) and stage.get("stage") == "route+intent"
        ),
        {},
    )
    model_selection = None
    if decision.get("model_proposal"):
        from src.app.services.llm_providers import invocation_version_trace

        recorded_invocation = (
            core.extras.get("model_invocation")
            if isinstance(core.extras.get("model_invocation"), dict) else {}
        )
        selected_model = str(
            recorded_invocation.get("model") or core.extras.get("llm_model") or "unknown"
        )
        provider = str(recorded_invocation.get("provider") or (
            "ollama" if selected_model != "unknown" else "unrecorded"
        ))
        invocation = invocation_version_trace(
            provider,
            selected_model,
            {
                "model_version": recorded_invocation.get("model_version"),
                "prompt_version": recorded_invocation.get("prompt_version") or "recommend-router-v2",
                "policy_version": recorded_invocation.get("policy_version") or "semantic-authority-v1",
            },
        )
        model_selection = {
            "selected": selected_model,
            **invocation,
            "source": decision.get("source") or "unknown",
            "authority": "proposes",
            "latency_ms": route_stage.get("latency_ms"),
        }
    semantic_resolution = core.extras.get("semantic_resolution") or {}
    workload_authorization = core.extras.get("workload_authorization") or {}
    material_fit_blocked = (
        str(semantic_resolution.get("catalog_authority") or "").lower() == "blocked"
        or str(workload_authorization.get("status") or "").lower() == "blocked"
    )
    slate_disposition = (
        "replace" if products
        else "retain" if clarifying and subject_action != "reset" and not material_fit_blocked
        else "clear"
    )
    payload: Dict[str, Any] = {
        **_universal(core),
        # ── the outcome (real core output) ────────────────────────────────────
        "assistant_message": core.message,
        "message": core.message,          # branch-duplicate field, kept for consumers
        "currency": core.envelope.currency,
        "products": products,
        "slate_disposition": slate_disposition,
        "results": products,              # recorded duplication — preserved at the edge
        "off_catalog": core.off_catalog,
        "refusal_note": core.refusal_note,
        "degraded": core.degraded,
        "needs_disambiguation": clarifying,
        "next_questions": core.clarify,
        "workload_fit": _workload_fit(core),
        # V2 recommendation-core presentation surfaces (Phase 1a-1d) — additive; the frontend
        # renders the 3-band shelf, the capability banner, advisories, and the stated assumption.
        # Absent (None/[]) on the legacy path, so old consumers are unaffected.
        "shelf": core.extras.get("shelf"),
        "capability": core.extras.get("capability"),
        "secondary_lanes": core.extras.get("secondary_lanes", []),
        "explanation": core.extras.get("explanation"),
        "advisories": core.extras.get("advisories", []),
        "assumption": core.extras.get("assumption"),
        "complement_offers": core.extras.get("complement_offers", []),
        "capability_conflict": core.extras.get("capability_conflict"),
        # Bulk quantities are consequential UI state: the storefront's Add action uses this value
        # to create the requested line quantity. Do not leave it trapped inside CoreResponse extras.
        "requested_quantity": core.extras.get("requested_quantity"),
        "bulk_budget": core.extras.get("bulk"),
        "availability": core.extras.get("availability"),
        "delivery_feasibility": core.extras.get("delivery_feasibility"),
        "human_escalation": core.extras.get("human_escalation"),
        "fulfillment_options": core.extras.get("fulfillment_options"),
        "sourcing_intent": core.extras.get("sourcing_intent"),
        "semantic_resolution": core.extras.get("semantic_resolution"),
        "semantic_requirement_compilation": core.extras.get("semantic_requirement_compilation"),
        "semantic_evidence": core.extras.get("semantic_evidence"),
        "approved_narration_evidence": core.extras.get("approved_narration_evidence", []),
        "catalog_alignment": core.extras.get("catalog_alignment"),
        "supplier_enquiry_option": core.extras.get("supplier_enquiry_option"),
        # Read-only procurement operations are a first-class compatibility contract.
        # Dropping these fields made the browser replace the current case with an empty
        # recommendation slate even though the V2 core correctly performed no retrieval.
        "preserve_current_view": bool(core.extras.get("preserve_current_view")),
        "case_operation": core.extras.get("case_operation"),
        "case_anchor": core.extras.get("case_anchor"),
        "state_changed": core.extras.get("state_changed"),
        "case_obligations": core.extras.get("case_obligations", []),
        "router_outcome": core.extras.get("router_outcome"),
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
        # Canonical V2 audit surface. ``agent_chain`` remains only for legacy consumers; these
        # typed rows make proposal, authorization, execution, observation, and presentation clear.
        "execution_steps": build_execution_steps(core),
        "ambiguity_reason": core.extras.get("ambiguity_reason"),
        "buyer_persona": None, "buyer_persona_candidate": None, "buyer_persona_confidence": None,
        "complexity_signals": core.extras.get("complexity_signals", {}),
        "confidence_band": core.extras.get("confidence_band", "unscored"),
        "confidence_calibrated": None,
        "constraints_used": constraints_used,
        "decision": decision,
        "intent": core.extras.get("intent", {}),
        "routing_source": (core.extras.get("decision") or {}).get("source"),
        "policy_source": core.extras.get("policy_source"),
        "policy_answered": bool(core.extras.get("policy_answered")),
        "counterfactual": None,
        "eligible": True,
        "evidence_items": core.extras.get("evidence_items", []),
        "evidence_weighting": {},
        "followup_contract": {},
        "intent_execution_plan": core.extras.get("plan", {}),
        "llm_model": core.extras.get("llm_model", "recommendation_core"),
        "model_selection": model_selection,
        "memory_confidence": None,
        "model_tier": core.extras.get("model_tier", "core"),
        "policy_version": "v1",
        "proposal": {"decision_mode": "recommendation_core",
                     "ranked_skus": [p.sku for p in core.products]},
        "question_plan": {"mode": "clarify" if clarifying else "none"},
        "referents": {"has_reference": False, "skus": [], "source": None},
        "view_mode": "grid",
        "view_reason": "recommendation_core",
        "timing_breakdown": dict(core.extras.get("timing_breakdown") or {}),
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
