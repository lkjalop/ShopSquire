"""The /suggest response contract — FROZEN 2026-07-11 (V2 Phase 0, roadmap §3 Phase 0).

Derived EMPIRICALLY from live captures on the P0-fixed build (c84d43f): a full search
response carries ~85 top-level fields, the off-catalog early-return branch ~40. This module
pins three things:

  1. KNOWN_FIELDS — every top-level field the live endpoint has been observed to emit.
     A V2 response emitting a field outside this set is a contract ADDITION (reviewable);
     a V1 field V2 stops emitting is a contract BREAK (must be justified against the corpus).
  2. CORE_FIELDS — the intersection present on EVERY branch (search / off-catalog /
     workload / early returns). V2 must always emit these.
  3. SuggestResponse — a permissive pydantic model typing the load-bearing fields.
     extra="allow" is deliberate: a characterization contract documents, it does not
     reject; drift detection is the differ's job (services/recommend_parity_full.py).

KNOWN CONTRACT QUIRKS (recorded, not endorsed — candidates for KNOWN_WRONG in the corpus):
  - `message` is emitted only by some branches (off-catalog / early returns);
    `assistant_message` is the universal field. Consumers must read assistant_message.
  - `turn_type` can read "zero_result_turn" on responses with 9 products (mislabel).
  - `products` and `results` are duplicates on every observed branch.
  - Transport: GET /api/v1/recommend/suggest (query params), auth header `x-api-key`,
    role merchant/owner/developer.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

# The TRUE universal contract — the ONLY fields present on every one of the 27 recorded
# turns across all branches (27-turn starter corpus, 2026-07-11). Everything else is
# branch-dependent. V1's real invariant is just: every response is traceable.
UNIVERSAL_FIELDS = frozenset({
    "trace_id", "decision_id", "decision_trace_id", "_trace_recommendation_persisted",
})

# Present on every FULL-PIPELINE branch (search / off-catalog / workload / clarify with
# retrieval). Alternate branches (below) do NOT emit these. V2's full-pipeline lane must.
CORE_FIELDS = frozenset({
    "_trace_recommendation_persisted", "agent_chain", "execution_steps", "ambiguity_reason", "assistant_message",
    "buyer_persona", "buyer_persona_candidate", "buyer_persona_confidence", "complexity_signals",
    "confidence_band", "confidence_calibrated", "constraints_used", "counterfactual",
    "decision_id", "decision_trace_id", "degraded", "eligible", "evidence_items",
    "evidence_weighting", "followup_contract", "intent_execution_plan", "llm_model",
    "memory_confidence", "model_tier", "needs_disambiguation", "policy_version", "products",
    "proposal", "question_plan", "referents", "results", "trace_id", "turn_type",
    "view_mode", "view_reason",
})

# Every top-level field observed live (union across branches, 2026-07-11). Grows as the
# corpus records more lanes (image, cart-mutate, procurement, claims) — append, don't prune.
KNOWN_FIELDS = frozenset(CORE_FIELDS | {
    "approval_id", "assumptions_applied", "autonomy_badge", "autonomy_tier", "b2b_assessment",
    "budget_fitness", "budget_viability", "catalog_profile", "catalog_relevance",
    "claim_guard_result", "drilldown_hidden_tags", "escalation", "escalation_assessment",
    "explicit_spec_blocks", "fraud", "hippograph_insights_shadow",
    "hippograph_shadow_counterfactual", "image_lane_fill", "image_reupload_reasons",
    "intent_confidence", "intent_router_model", "learn_more_url", "llm_summary_job_id",
    "memory_health", "message", "model_output_fingerprint", "model_watermark",
    "narration_mode", "narration_model", "next_questions", "notice", "off_catalog",
    "persona_tone", "policy_notes", "price_buckets", "price_filter", "price_range",
    "recommendation_tiers", "refusal_note", "requested_quantity", "right_panel", "risk_score",
    "slate_disposition",
    "sales_response_nudge", "security", "session_summary", "source_statuses",
    "storefront_emphasis", "summary_pending", "timing_breakdown", "trace_tags",
    # V2 bounded proposal and resolved intent are additive audit surfaces consumed by the
    # response finalizer. They expose model interpretation; they do not grant action authority.
    "decision", "intent",
    "turn_envelope_diff", "turn_intent", "use_case_analysis", "why_not", "workload_fit",
    # ── Alternate-branch fields (corpus 2026-07-11) — /suggest is a FORKED contract ──
    # inventory fast-path shape: answer/recommendations/inventory instead of
    # assistant_message/products (hit by stock-level queries, e.g. deficit_reorder case)
    "answer", "inventory", "nqe", "recommendations", "source", "timing", "injection_blocked",
    # claims/escalation shape (support_claim_damage case)
    "buyer_token", "human_review", "incident_id", "needs_human_review", "status",
    # policy/FAQ + clarify variants
    "availability", "fulfillment_options", "nqe_selection_applied",
    # Durable fast-lane audit hand-off and provider-neutral inventory source
    # selection. These are truth receipts, not recommendation authority.
    "_trace_recommendation_persistence_state", "_trace_recommendation_outbox_id",
    "inventory_tool_selection_receipt",
    # ── reviewed contract ADDITIONS (V2 recommendation_core, Phase 4) ──
    # grounding_status: taxonomy grounding state (grounded|empty|error) — degradation made
    # visible at the contract level instead of implied (added 2026-07-11 with legacy_adapter)
    "grounding_status",
    # V2 recommendation_core presentation surfaces (Phase 1a-1d, added 2026-07-13 with the shelf):
    # shelf = the 3-band right-side panel; capability = the floor/budget banner; advisories =
    # non-blocking notes (e.g. minor content-advisory); assumption = the stated variant assumption.
    "shelf", "capability", "secondary_lanes", "explanation", "advisories", "assumption",
    # complement_offers: declared complements (drawing → graphics tablet) as bundle-upsell (stocked)
    # or source-it supplier-RFQ offers (not stocked) — the unstocked-complement trust play (1d.4).
    "complement_offers",
    # capability_conflict: the catalog-derived 'these requirements can't coexist; relax X or Y' (1f).
    "capability_conflict",
    # bulk_budget: quantity/total/per-unit viability and authorized trade-off menu.
    "bulk_budget",
    # sourcing_intent: buyer-safe procurement preview. It contains no supplier identity and
    # materializes a fulfillment case only after the buyer confirms the cart.
    "sourcing_intent",
    # routing_source: model versus bounded fallback provenance used by promotion telemetry.
    "routing_source",
    # V2 ownership + immutable presentation identity. These make mixed-mode migration visible and
    # let every consumer prove it rendered the same trace-bound ordered product slate.
    "execution_mode", "execution_lane", "delegation_reason", "canonical_identity",
    # Authoritative settlement currency and truthful model proposal metadata. These prevent the
    # trace projector from guessing either value after the response has crossed the legacy edge.
    "currency", "model_selection",
    # Approved policy provenance: the answer came from the tenant StoreProfile, never invented
    # by the model. These fields were added with the independently owned policy lane.
    "policy_source", "policy_answered",
    # V2 semantic-authority and case-amendment surfaces (reviewed 2026-08-05). These fields
    # expose why catalog/commerce authority was withheld and preserve the current case view;
    # they do not allow the model to mutate catalog, cart, procurement, or payment state.
    "semantic_resolution", "semantic_evidence", "approved_narration_evidence",
    "semantic_requirement_compilation", "infrastructure_alternatives",
    "catalog_alignment", "supplier_enquiry_option", "preserve_current_view",
    "case_operation", "case_anchor", "state_changed",
    "case_obligations", "procurement_case_state", "case_patch_application",
    "router_outcome",
    # Post-catalog retrieval reality now adjudicates false authority. The
    # recommendation remains provisional unless positive fit evidence exists.
    "post_catalog_adjudication", "qualification_authority",
    # Deadline feasibility and its bounded human handoff are additive procurement evidence.
    "delivery_feasibility", "human_escalation",
})

# Observed branch shapes (detection heuristics used by validate_response):
#   full_pipeline  — has "products"/"results"; must carry CORE_FIELDS.
#   inventory_fast — has "recommendations"+"inventory"; the fork V2 must unify or honor.
#   claims         — has "incident_id"/"needs_human_review".
#   policy_faq     — has "status" without "products".


class SuggestResponse(BaseModel):
    """Typed view of the load-bearing fields. Everything else rides along via extra="allow"."""

    model_config = ConfigDict(extra="allow")

    # ── Universal message + result set ────────────────────────────────────────
    assistant_message: Optional[str] = None
    message: Optional[str] = None          # branch-dependent duplicate — see module quirks
    products: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []

    # ── Identity / trace ──────────────────────────────────────────────────────
    trace_id: Optional[str] = None
    decision_id: Optional[str] = None
    decision_trace_id: Optional[str] = None

    # ── Honesty rails (the fields the P0 fixes + audits guard) ────────────────
    off_catalog: Optional[Dict[str, Any]] = None    # {class,label,supplier_rfq_offer} when refusing
    refusal_note: Optional[str] = None
    requested_quantity: Optional[int] = None
    degraded: Optional[bool] = None

    # ── Turn semantics ────────────────────────────────────────────────────────
    turn_intent: Optional[str] = None
    turn_type: Optional[str] = None
    needs_disambiguation: Optional[bool] = None
    next_questions: Optional[List[Any]] = None
    constraints_used: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    intent: Optional[Dict[str, Any]] = None

    # ── Async narration handshake ─────────────────────────────────────────────
    llm_summary_job_id: Optional[str] = None
    summary_pending: Optional[bool] = None
    narration_mode: Optional[str] = None

    # ── Panels / fit truth ────────────────────────────────────────────────────
    right_panel: Optional[Dict[str, Any]] = None
    workload_fit: Optional[Dict[str, Any]] = None
    recommendation_tiers: Optional[Dict[str, Any]] = None

    # ── Governance surface ────────────────────────────────────────────────────
    security: Optional[Dict[str, Any]] = None
    autonomy_tier: Optional[str] = None
    escalation: Optional[Any] = None
    proposal: Optional[Dict[str, Any]] = None
    session_summary: Optional[Dict[str, Any]] = None


def response_shape(payload: Dict[str, Any]) -> str:
    """Which of the observed /suggest contract forks this payload belongs to.
    ORDER MATTERS (R10 census fix): a payload that SHOWS products is a product response —
    the legacy kitchen-sink can mint a claims artifact (incident_id, needs_human_review=True)
    on a PRODUCT turn (recorded live: compare_two_models carried both + 15 products), and
    classifying that 'claims' made the replay project V2 through the product-less claims
    adapter → a phantom empty. Claims shape = claims signal WITHOUT shown products."""
    if not isinstance(payload, dict):
        return "invalid"
    if "recommendations" in payload and "inventory" in payload:
        return "inventory_fast"
    if payload.get("products") or payload.get("results"):
        return "full_pipeline"
    if "incident_id" in payload or "needs_human_review" in payload:
        return "claims"
    if "products" in payload or "results" in payload:
        return "full_pipeline"
    if "status" in payload:
        return "policy_faq"
    return "unknown"


def validate_response(payload: Dict[str, Any]) -> List[str]:
    """Contract check for a live/recorded payload. Returns violation strings (empty = clean).
    Universal (trace identity) fields are required on EVERY shape; CORE fields only on the
    full-pipeline shape; unknown fields are additions (informational)."""
    problems: List[str] = []
    if not isinstance(payload, dict):
        return [f"payload is {type(payload).__name__}, expected dict"]
    shape = response_shape(payload)
    for f in sorted(UNIVERSAL_FIELDS - set(payload)):
        problems.append(f"missing universal field: {f}")
    if shape == "full_pipeline":
        for f in sorted(CORE_FIELDS - set(payload)):
            problems.append(f"missing core field: {f}")
    for f in sorted(set(payload) - KNOWN_FIELDS):
        problems.append(f"unknown field (contract addition?): {f}")
    am = payload.get("assistant_message")
    if am is not None and not isinstance(am, str):
        problems.append("assistant_message is not a string")
    for key in ("products", "results"):
        if key in payload and not isinstance(payload[key], list):
            problems.append(f"{key} is not a list")
    oc = payload.get("off_catalog")
    if oc is not None:
        if not isinstance(oc, dict):
            problems.append("off_catalog is not a dict")
        elif payload.get("products"):
            problems.append("off_catalog set but products non-empty (honesty violation)")
    return problems
