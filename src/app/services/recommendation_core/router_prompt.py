"""Presentation-free prompt assembly for the bounded turn interpreter."""
from __future__ import annotations

from functools import lru_cache

from src.app.services.recommendation_core.envelope import LANES


@lru_cache(maxsize=8)
def _instruction_prefix(req_keys: tuple[str, ...], use_case_keys: tuple[str, ...]) -> str:
    """Stable prefix first, allowing the model server to reuse its prompt/KV prefix."""
    from src.app.services.recommendation_core.intent_resolver import audience_context_keys
    context_keys = tuple(audience_context_keys())
    workload_keys = tuple(key for key in use_case_keys if key not in context_keys)
    return (
        "Route one commerce turn into bounded JSON. The model interprets language; the platform "
        "validates every category, product, constraint and action.\n"
        f"LANES: {', '.join(LANES)}. Pick one. POLICY_QUESTION is general payment/delivery/returns "
        "policy only. For an active procurement, RFQ drafts, supplier channels, requested delivery "
        "dates, quantities, budgets, MOQ blockers, send status, and keep/change-constraint turns are "
        "PROCUREMENT (or FILTER for a product-only refinement), not POLICY_QUESTION. Questions such "
        "as 'which supplier channel would be used?' and 'has the supplier draft been sent?' are "
        "PROCUREMENT status questions. Requests to pause, retain, resume, or keep a sourcing request "
        "as a draft are also PROCUREMENT. A price-affordability question by itself ('is $X enough "
        "for a laptop?') is SEARCH/FILTER, not PROCUREMENT; PROCUREMENT requires a quantity, supplier, "
        "quote/RFQ, sourcing/reorder action, or an existing procurement case.\n"
        "Set procurement_context=current_order only when the message concerns the active order, "
        "sourcing case, supplier interaction, quantity, delivery plan, or RFQ; set general_policy "
        "for store-wide delivery/returns/payment policy; otherwise none.\n"
        "EXPLAIN is for why a prior recommendation or 'the first one' fits; COMPARE is for explicit "
        "side-by-side product comparisons. Do not turn an explanation follow-up into COMPARE.\n"
        "Pick what the shopper wants to buy, not a mentioned object. A game, application or "
        "workload maps to the device that runs it. OFF_CATALOG is only for a clearly unsold "
        "category. Buy/quote/source/do-you-sell requests remain commerce even when no exact "
        "candidate exists: use OFF_CATALOG. If no candidate handle fits, wanted_category MUST "
        "name the specific taxonomy-style leaf being requested, include its parent noun when the "
        "leaf is ambiguous, and name the requested product rather than its parts or accessories. "
        "Translate coined workload/form-factor wording to the standard category of the complete "
        "product instead of repeating the shopper's phrase. "
        "It MUST NOT be null. A non-product "
        "service/location request uses SEARCH with handle=null, request_scope=service_or_place, "
        "and confidence=0; lane itself is "
        "never null. Prefer an [in catalog] sibling only when meaning is otherwise equivalent.\n"
        f"WORKLOAD_USE_CASE keys: {', '.join(workload_keys)}. Name zero or more in use_cases; "
        "do not put the buyer's school/audience context there and do not invent hardware "
        "floors because the platform resolves those from evidence. When a listed bounded variant "
        "materially describes the PRIMARY workload, return its exact scalar name in "
        "use_case_variant. It must belong to one selected use case. Use null when uncertain.\n"
        f"AUDIENCE_CONTEXT keys: {', '.join(context_keys)}. Put explicit buyer context in "
        "audience_contexts. Context affects explanation/preferences and never weakens workload floors.\n"
        f"REQUIREMENT keys: {', '.join(req_keys)}. Extract only explicit numeric specs in an "
        "object mapping key to [operator,number]. Price and item count are not specs.\n"
        "OPERATIONAL_CONSTRAINTS are not product specs. Put an explicitly requested relative "
        "delivery window in delivery_window_days. Put an explicit payment preference in "
        "payment_plan using only full_payment, deposit, balance_after_confirmation, or b2b_terms. "
        "These are proposals; calendar, provider and policy services authorize them.\n"
        "WORKLOAD_ENTITIES: copy at most three explicitly named games or software applications "
        "from the message as {kind: game|software, name: literal title}. Never infer names.\n"
        "SEMANTIC_PROPOSAL: when unfamiliar or materially ambiguous wording could change whether "
        "a product is suitable, emit one generic resolution record. Put the exact buyer wording "
        "in concepts.query_span and concepts.text. You may add an advisory normalized_label, but "
        "do not invent product facts. Include desired_outcome; zero to five product_category_candidates "
        "as proposed labels; concepts (text, query_span, normalized_label, status=unresolved|ambiguous, "
        "material, optional interpretations); zero to five competing workload_hypotheses with a stable "
        "hypothesis_id, label, evidence_needed, confidence, and authority=proposed. A hypothesis may "
        "name required_claim_types only from concept_identity, minimum_requirements, "
        "recommended_requirements, target_requirements, compatibility, certification, and may name "
        "discriminating_unknown_ids that exist in material_unknowns; and material_unknowns "
        "classified by resolution_source=research|buyer|either. Hypotheses are alternatives to investigate, "
        "never accepted facts. Each evidence_question must name resolves_unknown_ids and one or more bounded "
        "decision_impacts from architecture, capability, affordable_quantity, product_set. Ask buyers only "
        "about unknowns classified buyer or either; official requirements belong to research. Include only "
        "questions whose answers could change catalog fit, proposed_action, and confidence. Omit the entire "
        "object when the request is already specific enough for catalog search.\n"
        "REFINE: brand=hard-only, prefer_brand=soft, exclude_brand=negation, sort=price_asc, "
        "price_desc or null. brand_action=keep when brands are unmentioned, set when adding or "
        "replacing a brand constraint, clear only when the shopper explicitly removes all brand "
        "constraints. compare_targets contains only specifically named products. When a prior "
        "product subject exists and the message only changes brand, sort, budget, capability "
        "filters, or quantity without switching category, use FILTER (or PROCUREMENT for the "
        "active order). A sort-only continuation is FILTER, not a new SEARCH.\n"
        "BULK: quantity is unit count; total_budget is whole-order dollars; budget_scope is "
        "per_unit, total or null. Never reinterpret per-unit as total. budget_cap_mode is hard "
        "for explicit limits, soft for approximate targets, ambiguous when the wording is unclear.\n"
        "CASE_PATCHES: propose explicit buyer case facts as typed operations; never rewrite the "
        "entire prior case. Allowed operations are set, add, remove and move_quantity. Allowed "
        "paths are objective, workloads, selected_sku, requested_quantity, destinations, "
        "budget.amount_minor, budget.currency, budget.scope, temporal.original_expression, "
        "temporal.required_by, temporal.timezone. For a stated multi-location allocation, set "
        "destinations to rows of {location_ref, quantity, location_kind}. For 'move 5 from Perth "
        "to Sydney', emit one move_quantity patch with path=destinations, quantity=5, from_ref "
        "and to_ref; do not repeat unchanged workload, budget, deadline or total. Use amount_minor "
        "for money. Preserve relative time as temporal.original_expression; only emit required_by "
        "when the input/session supplies an unambiguous timezone-aware timestamp. These are state "
        "proposals only and never authorize cart, RFQ, payment or shipment.\n"
        "For a product request where no [in catalog] candidate fits, lane MUST be OFF_CATALOG. "
        "Include either its offered unstocked handle or a specific wanted_category; do not emit "
        "a nodeless SEARCH. SEARCH with no handle is only for a non-product service or place.\n"
        "Return ONLY one sparse JSON object. Always include lane. Omit optional fields when "
        "their value would be null, empty, unchanged, or unknown; the platform supplies bounded "
        "defaults. Allowed optional keys: handle, wanted_category, request_scope, use_cases, "
        "workload_entities, "
        "audience_contexts, use_case_variant, requirements, refine, compare_targets, quantity, "
        "total_budget, budget_scope, budget_cap_mode, subject_action, procurement_context, "
        "operational_constraints, "
        "confidence, semantic_proposal, clarification_relation, case_patches. Inside refine, emit only changed keys from brand, prefer_brand, "
        "exclude_brand, sort, brand_action. Never add prose or keys outside this contract.\n")


def compose_router_prompt(
    *, instruction_prefix: str, guide: str, variants: str, prior_context: str,
    pending_context: str, message: str, budget: str, image: str, research: str,
    candidate_lines: str,
) -> str:
    """Compose already-sanitized bounded sections in one stable order."""
    return (
        instruction_prefix + "\n" + guide + variants + prior_context + pending_context
        + f'MESSAGE: "{message[:400]}"\n' + budget + image + research
        + "CANDIDATE CATEGORIES (listed handle or null only):\n" + candidate_lines
        + "\nResolve MESSAGE now. Do not copy the schema's example values. For a product-commerce "
        "request with no fitting handle, return OFF_CATALOG and a specific non-null "
        "wanted_category; avoid ambiguous umbrella nouns, coined phrases, and accessory "
        "categories.\nJSON:"
    )


__all__ = ["_instruction_prefix", "compose_router_prompt"]
