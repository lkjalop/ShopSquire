"""The orchestrator (V2 Phase 4, step 3) — recommend_turn(): one routed, planned, grounded,
finalized turn. This is what replaces suggest()'s 7,250 lines of implicit line-order.

Explicit sequence, no hidden state, every decision attributable:
    grounding check → route (model judgment, 4 clamps) → plan (closed vocabulary)
    → execute steps (deterministic tools) → finalize (type-level honesty invariants)
    → [caller: legacy_adapter.to_legacy() for the recorded contract shapes]

Every stage's outcome lands in CoreResponse.extras — the turn is REPLAYABLE from its own
breadcrumbs, which is what the shadow differ diffs against the oracle.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from src.app.services.recommendation_core.envelope import CoreResponse, TurnEnvelope
from src.app.services.recommendation_core.evidence import (
    degraded_response,
    gather_evidence,
)
from src.app.services.recommendation_core.fit import build_cards
from src.app.services.recommendation_core.plan import Plan, derive_plan
from src.app.services.recommendation_core.turn_router import TurnDecision, route_turn
from src.app.services.taxonomy_registry import grounding_status

logger = logging.getLogger("shopsquire.recommendation_core.core")

LLMFn = Callable[[str, float], str]


def recommend_turn(db, envelope: TurnEnvelope, *, llm_fn: Optional[LLMFn] = None,
                   limit: int = 10) -> CoreResponse:
    """Never raises. The response is always finalized (honesty invariants enforced)."""
    try:
        return _recommend_turn(db, envelope, llm_fn=llm_fn, limit=limit)
    except Exception as exc:  # the never-raise floor: degraded honesty, loudly logged
        logger.exception("recommendation_core turn failed: %s", exc)
        return degraded_response(envelope, reason=f"core_error:{type(exc).__name__}")


def _recommend_turn(db, envelope: TurnEnvelope, *, llm_fn: Optional[LLMFn],
                    limit: int) -> CoreResponse:
    grounding = grounding_status(db, tenant_id=envelope.tenant_id)
    # M1.1 UNGROUNDED GUARD (clickthrough issue #1): the core hard-depends on the tenant's
    # sold_taxonomy/classifications. An 'empty' tenant (never onboarded) would otherwise degrade
    # SILENTLY — no refusals, arbitrary text-search retrieval, 'nothing meets'. Short-circuit
    # BOTH here (before the ~7s model call), preserving the true grounding so the facade falls
    # to legacy (canary/primary) and telemetry distinguishes infra-error from not-onboarded.
    if grounding in ("error", "empty"):
        reason = "taxonomy_grounding_error" if grounding == "error" else "catalog_not_onboarded"
        return degraded_response(envelope, reason=reason, grounding=grounding)

    import dataclasses
    from src.app.services.recommendation_core.intent_resolver import resolve as resolve_intent
    decision = route_turn(db, envelope, llm_fn=llm_fn)
    # INTENT → REQUIREMENTS: the model NAMED the use-case(s); deterministic KB lookup supplies
    # the hardware requirements and merges them (by MAX) with any the shopper stated explicitly.
    # This is what makes a CS student differ from an english major and 'for AutoCAD' carry real
    # floors — all from DATA, no new decision surface. Zero added latency (folded into routing).
    intent = resolve_intent(list(decision.use_cases), dict(decision.requirements),
                            query=envelope.query)
    decision = dataclasses.replace(decision, requirements=intent["requirements"])
    plan = derive_plan(decision)   # model plan refinement arrives with the plan-proposal leg

    resp = CoreResponse(envelope=envelope, lane=decision.lane, grounding=grounding)
    resp.extras["decision"] = decision.as_dict()
    resp.extras["plan"] = plan.as_dict()
    # the resolver's reasoning, surfaced for the 'Why Recommended' decision-trace tab
    resp.extras["intent"] = {"use_cases": intent["use_cases"],
                             "profiles": intent["profile_trace"],
                             "title_requirements": intent.get("title_requirements") or {},
                             "persona_hint": intent["persona_hint"]}
    resp.extras["constraints_used"] = {
        "budget_min_cents": envelope.budget_min_cents,
        "budget_max_cents": envelope.budget_max_cents,
        "node_handle": decision.node_handle,
        "requirements": {k: list(v) for k, v in decision.requirements.items()},
        "use_cases": intent["use_cases"],
    }

    for step in plan.steps:
        _EXECUTORS[step](db, envelope, decision, resp, limit)

    # gates: prefer the SHARED commerce guard's verdict (run once at the facade ingress) —
    # the core does NOT own a second security regex (GPT-5.6 #10). The thin evaluate_text_gates
    # is the NO-FACADE fallback only (offline replay / direct tests).
    from src.app.services.recommendation_core.gates import evaluate_text_gates, slot_gap_clarify
    if envelope.pre_gate is not None:
        pg = envelope.pre_gate
        route = "allow" if str(pg.get("verdict") or "allow") == "allow" else "review"
        gates = {"policy_route": route, "image_untrusted": bool(envelope.has_image),
                 "injection_flagged": route != "allow", "source": "commerce_request_guard"}
    else:
        gates = evaluate_text_gates(envelope.query)
    resp.extras["gates"] = gates
    if gates["policy_route"] != "allow":
        resp.degraded = True

    # clarify (census bucket 2): v1's NQE equivalent as deterministic slot-gap UX policy
    if not resp.off_catalog and not resp.clarify:
        q = slot_gap_clarify(
            has_products=bool(resp.products),
            budget_known=envelope.budget_max_cents is not None or envelope.budget_min_cents is not None,
            has_requirements=bool(decision.requirements))
        if q:
            resp.clarify.append(q)
    return resp.finalize()


# ── the deterministic tool executors (the plan vocabulary's other half) ───────

def _exec_retrieve(db, envelope: TurnEnvelope, decision: TurnDecision,
                   resp: CoreResponse, limit: int) -> None:
    bundle = gather_evidence(db, envelope, node_handle=decision.node_handle,
                             limit=max(limit * 3, 30))
    # broad-retry ONLY on a valid empty (never on error — that would mask a failure): no node
    # matched and the phrase LIKE-matches nothing ('play valorant at 144fps') but we HAVE
    # clamped requirements = retrieval intent enough; rank the catalog by fit (closest-match
    # honesty beats an empty grid).
    if bundle.status == "empty" and decision.requirements:
        bundle = gather_evidence(db, envelope, broad=True, limit=max(limit * 5, 60))
        bundle.retrieval_mode = "requirements_broad"
    resp.extras["evidence"] = bundle.as_trace()
    if bundle.status == "error":
        resp.degraded = True         # a retrieval FAILURE degrades — never present as 'no match'
        return
    cards, summary = build_cards(bundle.variants, decision.requirements or None, limit=limit)
    resp.products = cards
    if decision.requirements:
        resp.fit_summary = summary
        if summary.get("closest_match_mode"):
            reqs = ", ".join(f"{k} {op} {int(t) if float(t).is_integer() else t}"
                             for k, (op, t) in decision.requirements.items())
            resp.message = (f"No product in our catalog meets {reqs} — showing the closest "
                            f"options, ranked by how near they come.")


def _exec_fit_check(db, envelope: TurnEnvelope, decision: TurnDecision,
                    resp: CoreResponse, limit: int) -> None:
    # fit is computed inside retrieve when requirements exist; this step exists so a model
    # plan can DEMAND a verdict pass — it re-ranks if retrieve ran without requirements
    if decision.requirements and resp.products and resp.fit_summary is None:
        cards, summary = build_cards(
            [c for c in resp.products if c], None, limit=limit)  # already carded: no-op guard
        resp.fit_summary = resp.fit_summary or {"requirements": {}, "meets": 0, "unknown": 0,
                                                "fails": 0, "closest_match_mode": False}


def _exec_off_catalog(db, envelope: TurnEnvelope, decision: TurnDecision,
                      resp: CoreResponse, limit: int) -> None:
    # only reachable with refusal_granted (router clamp AND plan validator both enforce it)
    node_label = decision.node_path or "that category"
    resp.off_catalog = {"class": decision.node_handle, "label": node_label,
                        "supplier_rfq_offer": True}


def _exec_clarify(db, envelope: TurnEnvelope, decision: TurnDecision,
                  resp: CoreResponse, limit: int) -> None:
    resp.clarify.append({"question": "Could you tell me a bit more about what you need "
                                     "(budget, brand, or intended use)?",
                         "reason": "low_routing_confidence"})


def _exec_policy_answer(db, envelope: TurnEnvelope, decision: TurnDecision,
                        resp: CoreResponse, limit: int) -> None:
    # capability honesty rides the registry until the policy lane lands in a later step
    resp.extras["policy_topic"] = envelope.query[:120]
    resp.message = ("Good question — our policy details are being routed to the right lane; "
                    "here's what I can confirm from the store profile.")


def _exec_handoff_support(db, envelope: TurnEnvelope, decision: TurnDecision,
                          resp: CoreResponse, limit: int) -> None:
    resp.extras["needs_human_review"] = True
    resp.extras["claim_status"] = "received"
    resp.message = ("I've logged this as a support claim — a human will review it. "
                    "You'll be contacted with next steps.")


def _exec_handoff_procurement(db, envelope: TurnEnvelope, decision: TurnDecision,
                              resp: CoreResponse, limit: int) -> None:
    resp.extras["procurement_intent"] = True
    resp.message = ("This looks like a bulk/procurement request — I can draft a supplier "
                    "quote request for review. Nothing is sent without human approval.")


_EXECUTORS: Dict[str, Any] = {
    "retrieve": _exec_retrieve,
    "fit_check": _exec_fit_check,
    "off_catalog_honesty": _exec_off_catalog,
    "clarify": _exec_clarify,
    "policy_answer": _exec_policy_answer,
    "handoff_support": _exec_handoff_support,
    "handoff_procurement": _exec_handoff_procurement,
}
