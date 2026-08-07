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

import dataclasses
import hashlib
import logging
import os
import re
import time
from typing import Any, Callable, Dict, Optional

from src.app.services.recommendation_core.envelope import CoreResponse, MsgPriority, TurnEnvelope
from src.app.services.recommendation_core.evidence import (
    degraded_response,
    gather_evidence,
)
from src.app.services.recommendation_core.fit import build_cards
from src.app.services.recommendation_core.plan import derive_plan
from src.app.services.recommendation_core.turn_router import (
    TurnDecision,
    active_router_model,
    last_router_call_metrics,
    route_turn,
)
from src.app.services.taxonomy_registry import (
    ancestors,
    classification_nodes_for_skus,
    get_node,
    grounding_status,
)

logger = logging.getLogger("shopsquire.recommendation_core.core")

LLMFn = Callable[[str, float], str]

_EXPLICIT_CONTEXT_RESET = re.compile(
    r"\b(?:start\s+over|new\s+search|forget\s+(?:that|those|the\s+previous)|"
    r"switch\s+(?:products?|categories?|to))\b",
    re.IGNORECASE,
)


def _is_descendant_or_self(node_handle: str, root: str) -> bool:
    """True when node_handle is root or a descendant of root (ancestry is string-encoded:
    el-6-11-2 ⊂ el-6-11 ⊂ el-6)."""
    if not node_handle or not root:
        return False
    if node_handle == root:
        return True
    return any(a.handle == root for a in ancestors(node_handle))


def _is_workload_host_product(node_handle: Optional[str]) -> bool:
    """review-8 #4: is the REQUESTED product a device that can host a workload? Only such products
    inherit a use-case/workload's device floors. Reads the store profile's workload_host_roots
    (Computers subtree); an accessory (mouse/bag/case) is not under it, so 'a mouse for gaming'
    does NOT get gpu_vram_gb/ram_gb floors. Unknown node / no profile → treat as host (fail-open:
    never DROP a floor we're unsure about; the broad-retry vertical scoping is the safety net)."""
    if not node_handle:
        return True
    try:
        from src.app.platform.store_profile import profile_slot
        roots = profile_slot("workload_host_roots", default=None)
        if not roots:
            return True
        return any(_is_descendant_or_self(node_handle, str(r)) for r in roots)
    except Exception as exc:
        logger.debug("workload_host_roots lookup failed: %s", repr(exc)[:100])
        return True


def _first_workload_host_root() -> Optional[str]:
    """A device-subtree root to scope a broad retry to when NO node routed but device requirements
    exist (the safety net behind the ungrounded-workload reroute). Reads workload_host_roots."""
    try:
        from src.app.platform.store_profile import profile_slot
        roots = profile_slot("workload_host_roots", default=None) or []
        return str(roots[0]) if roots else None
    except Exception as exc:
        logger.debug("workload_host_roots lookup failed: %s", repr(exc)[:100])
        return None


def _vertical_root(node_handle: Optional[str]) -> Optional[str]:
    """The depth-0 taxonomy ancestor (vertical root) of a node — el-7-9-12-11 → el. Used to keep a
    broad retry INSIDE the requested product's vertical (electronics stays electronics; pharmacy is
    a different tree, hb-*) so an empty-node fallback can never bleed across verticals."""
    node = get_node(node_handle) if node_handle else None
    if node is None:
        return None
    if node.depth == 0:
        return node.handle
    for a in ancestors(node_handle):
        if a.depth == 0:
            return a.handle
    return None


def _run_stage(resp: CoreResponse, name: str, fn: Callable[[], None]) -> None:
    """Run one guarded post-retrieval stage (P0.5): time it, record a telemetry breadcrumb, and
    swallow-but-log any failure — a stage failure must never break the turn (the products already
    stand on their own). won_message is inferred from whether the message-priority slot advanced,
    so the trace shows exactly which stage authored the buyer's sentence."""
    t0 = time.perf_counter()
    prio_before = resp._msg_priority
    status = "ok"
    try:
        fn()
    except Exception as exc:
        status = "error"
        logger.warning("%s stage skipped: %s", name, repr(exc)[:120])
    resp.record_stage(name, status=status,
                      latency_ms=(time.perf_counter() - t0) * 1000.0,
                      won_message=resp._msg_priority > prio_before)


def build_timing_breakdown(
    core: CoreResponse, *, total_ms: float, router_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Project one request-scoped timing contract from typed stage results.

    ``retrieval_ms`` is diagnostic and contained within ``plan_ms``. Keeping that relationship
    explicit prevents operators from adding overlapping phases and inventing a larger total.
    """
    stages = [item.as_dict() for item in core.stage_results]
    route_ms = sum(
        float(item.get("latency_ms") or 0.0)
        for item in stages if item.get("stage") == "route+intent"
    )
    plan_ms = sum(
        float(item.get("latency_ms") or 0.0)
        for item in stages if str(item.get("stage") or "").startswith("plan:")
    )
    post_stages = [
        item for item in stages
        if item.get("stage") != "route+intent"
        and not str(item.get("stage") or "").startswith("plan:")
    ]
    post_ms = sum(float(item.get("latency_ms") or 0.0) for item in post_stages)
    fulfillment_ms = sum(
        float(item.get("latency_ms") or 0.0)
        for item in post_stages if item.get("stage") == "fulfillment_preview"
    )
    retrieval_ms = float((core.extras.get("evidence") or {}).get("latency_ms") or 0.0)
    model = dict(router_metrics or {})
    router_queue_ms = float(model.get("queue_ms") or 0.0)
    router_load_ms = float(model.get("load_ms") or 0.0)
    router_prefill_ms = float(model.get("prompt_eval_ms") or 0.0)
    router_decode_ms = float(model.get("decode_ms") or 0.0)
    router_wall_ms = float(model.get("wall_ms") or 0.0)
    router_provider_overhead_ms = max(
        0.0,
        router_wall_ms
        - router_queue_ms
        - router_load_ms
        - router_prefill_ms
        - router_decode_ms,
    )
    return {
        "recommendation_total_ms": round(float(total_ms), 1),
        "route_total_ms": round(route_ms, 1),
        "plan_ms": round(plan_ms, 1),
        "retrieval_ms": round(retrieval_ms, 1),
        "post_stage_ms": round(post_ms, 1),
        "fulfillment_preview_ms": round(fulfillment_ms, 1),
        "router_queue_ms": round(router_queue_ms, 1),
        "router_load_ms": round(router_load_ms, 1),
        "router_prefill_ms": round(router_prefill_ms, 1),
        "router_decode_ms": round(router_decode_ms, 1),
        "router_provider_overhead_ms": round(router_provider_overhead_ms, 1),
        "router_wall_ms": round(router_wall_ms, 1),
        "router_outcome": str(model.get("outcome") or "not_called"),
        "router_model": str(model.get("model") or "not_called"),
        "retrieval_contained_in_plan": True,
        "stages": stages,
    }


def recommend_turn(db, envelope: TurnEnvelope, *, llm_fn: Optional[LLMFn] = None,
                   limit: int = 10) -> CoreResponse:
    """Never raises. The response is always finalized (honesty invariants enforced)."""
    started = time.perf_counter()
    try:
        core = _recommend_turn(db, envelope, llm_fn=llm_fn, limit=limit)
    except Exception as exc:  # the never-raise floor: degraded honesty, loudly logged
        logger.exception("recommendation_core turn failed: %s", exc)
        core = degraded_response(envelope, reason=f"core_error:{type(exc).__name__}")
    router_metrics = (
        last_router_call_metrics()
        if any(item.stage == "route+intent" for item in core.stage_results)
        else {}
    )
    core.extras["timing_breakdown"] = build_timing_breakdown(
        core,
        total_ms=(time.perf_counter() - started) * 1000.0,
        router_metrics=router_metrics,
    )
    return core


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
    from src.app.services.budget_grammar import parse_budget_delta

    # A relative budget instruction is authorized only against the immutable
    # accepted session value. Apply it before routing/retrieval so every later
    # stage sees the same bounded envelope; never reinterpret the delta as an
    # absolute cap.
    _accepted_before_route = (envelope.session or {}).get("accepted_constraints") or {}
    _budget_delta = parse_budget_delta(envelope.query)
    _prior_budget_max = _accepted_before_route.get("budget_max_cents")
    if _budget_delta is not None and _prior_budget_max is not None:
        try:
            _updated_budget_max = int(_prior_budget_max) + (_budget_delta * 100)
            _prior_budget_min = _accepted_before_route.get("budget_min_cents")
            _updated_budget_min = (
                int(_prior_budget_min) + (_budget_delta * 100)
                if _prior_budget_min is not None
                else None
            )
        except (TypeError, ValueError):
            _updated_budget_max = 0
            _updated_budget_min = None
        if _updated_budget_max > 0:
            envelope = dataclasses.replace(
                envelope,
                budget_min_cents=(
                    _updated_budget_min
                    if _updated_budget_min is not None and _updated_budget_min > 0
                    else None
                ),
                budget_max_cents=_updated_budget_max,
            )

    from src.app.services.recommendation_core.intent_resolver import resolve as resolve_intent
    # time the whole DECIDE phase (the ~7s router model call + KB intent resolution + reroute +
    # continuation inheritance) — this is the turn's dominant latency, so the canary can attribute
    # the p50 to the model call vs the deterministic stages (P1 instrumentation).
    _t_route = time.perf_counter()
    from src.app.services.recommendation_core.turn_router import router_runtime_contract

    router_contract = router_runtime_contract()
    decision = route_turn(
        db,
        envelope,
        llm_fn=llm_fn,
        timeout=float(router_contract["inference_timeout_s"]),
    )
    # Monetary changes require buyer-supplied evidence. A BYO router may propose a number
    # even when the turn only says "keep the total budget"; accepting that proposal would
    # let narration silently rewrite an order constraint. The canonical grammar is the
    # authorization boundary: without a parsed amount, discard a new model amount. When the
    # buyer explicitly names total/per-unit scope and a prior value exists, preserve it.
    from src.app.services.budget_grammar import classify_budget_scope, parse_budget
    _parsed_turn_budget = parse_budget(envelope.query)
    _explicit_turn_scope = classify_budget_scope(envelope.query)
    _accepted = (envelope.session or {}).get("accepted_constraints") or {}
    # A consent retry is semantically the same turn. Sparse model output may omit an unchanged
    # workload title, so adopt a prior title only when every normalized title token still occurs
    # in the current message. This prevents an old game from contaminating a new query.
    if not decision.workload_entities and envelope.external_research_consent:
        prior_entities = _accepted.get("workload_entities") or []
        query_tokens = set(re.findall(r"[a-z0-9]+", (envelope.query or "").lower()))
        inherited_entities = []
        for item in list(prior_entities)[:3]:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            kind, name = str(item[0]), str(item[1])
            name_tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
            if kind in ("game", "software") and name_tokens and name_tokens <= query_tokens:
                inherited_entities.append((kind, name))
        if inherited_entities:
            decision = dataclasses.replace(
                decision, workload_entities=tuple(inherited_entities))
    if _parsed_turn_budget is None and decision.total_budget_cents is not None:
        decision = dataclasses.replace(decision, total_budget_cents=None)
    if _parsed_turn_budget is None and _explicit_turn_scope == "total":
        _prior_total = _accepted.get("total_budget_cents")
        decision = dataclasses.replace(
            decision,
            total_budget_cents=(int(_prior_total) if _prior_total is not None else None),
            budget_scope="total",
            quantity=(decision.quantity if decision.quantity is not None
                      else (int(_accepted["quantity"]) if _accepted.get("quantity") else None)),
        )
    elif (_parsed_turn_budget is None and decision.lane == "FILTER"
          and decision.subject_action == "continue"
          and str(_accepted.get("budget_scope") or "") == "total"
          and _accepted.get("total_budget_cents") is not None):
        # A constraint-only continuation keeps the authorized whole-order cap. A new quantity
        # changes affordability arithmetic, not the meaning or amount of the budget.
        decision = dataclasses.replace(
            decision,
            total_budget_cents=int(_accepted["total_budget_cents"]),
            budget_scope="total",
            quantity=(decision.quantity if decision.quantity is not None
                      else (int(_accepted["quantity"]) if _accepted.get("quantity") else None)),
        )
    # Constraint-only updates preserve the last authorized sold subject even when a BYO
    # router incorrectly labels the turn as a switch or returns no node. This is a core
    # authorization invariant, not an intent heuristic: the canonical budget parser proves
    # the bounded constraint, and the prior node was already sellability-clamped.
    if decision.node_handle is None and (envelope.session or {}).get("prior_node"):
        try:
            prior = get_node(str((envelope.session or {}).get("prior_node") or ""))
            if (
                (parse_budget(envelope.query) is not None or decision.requirements)
                and prior is not None
            ):
                decision = dataclasses.replace(
                    decision,
                    node_handle=prior.handle,
                    node_path=prior.full_path,
                    requested_product_node=prior.handle,
                    subject_from_session=True,
                    subject_action="continue",
                )
        except Exception as exc:
            logger.debug(
                "Prior subject continuation skipped: %s",
                repr(exc)[:120],
            )
    # A budget-only amendment changes the amount, not the already answered scope.
    # During a provider outage the bounded router can correctly preserve the prior
    # product while returning ``unknown`` for scope.  Reopening the material
    # per-unit/total question here contradicts the sealed buyer answer and leaves
    # the response internally inconsistent (confirmed_slots says per_unit while
    # the decision asks again).  Inherit only a previously accepted closed-vocabulary
    # scope and only when this turn contains a canonically parsed amount; fresh
    # product requests and scope-free conversation remain unaffected.
    if (
        _parsed_turn_budget is not None
        and decision.subject_action == "continue"
        and decision.budget_scope == "unknown"
    ):
        _prior_scope = str(_accepted.get("budget_scope") or "").strip().lower()
        if _prior_scope in {"per_unit", "total"}:
            decision = dataclasses.replace(decision, budget_scope=_prior_scope)
    # The HTTP contract may not pre-parse a textual budget.  The model maps its value and
    # scope; deterministic arithmetic turns that bounded proposal into the per-unit ceiling
    # used by evidence retrieval.  A total budget for N units is never treated as per-unit.
    if decision.budget_scope == "total" and decision.quantity:
        quantity = max(1, decision.quantity)
        total_max = decision.total_budget_cents or envelope.budget_max_cents
        envelope = dataclasses.replace(
            envelope,
            budget_min_cents=(envelope.budget_min_cents // quantity
                              if envelope.budget_min_cents is not None else None),
            budget_max_cents=(total_max // quantity if total_max is not None else None),
        )
    elif (envelope.budget_min_cents is None and envelope.budget_max_cents is None
          and decision.total_budget_cents is not None):
        per_unit_cap = None
        if decision.budget_scope == "per_unit":
            per_unit_cap = decision.total_budget_cents
        elif decision.quantity in (None, 1):
            per_unit_cap = decision.total_budget_cents
        if per_unit_cap and per_unit_cap > 0:
            envelope = dataclasses.replace(envelope, budget_max_cents=int(per_unit_cap))
    # INTENT → REQUIREMENTS: the model NAMED the use-case(s); deterministic KB lookup supplies
    # the hardware requirements and merges them (by MAX) with any the shopper stated explicitly.
    # This is what makes a CS student differ from an english major and 'for AutoCAD' carry real
    # floors — all from DATA, no new decision surface. Zero added latency (folded into routing).
    stated_keys = set(decision.requirements)   # what the SHOPPER explicitly asked for (pre-KB)
    intent = resolve_intent(list(decision.use_cases), dict(decision.requirements),
                            query=envelope.query,
                            vertical=_vertical_name(decision.node_handle),
                            use_case_variants=dict(decision.use_case_variants),
                            workload_entities=list(decision.workload_entities),
                            external_research_consent=envelope.external_research_consent)
    resolved_reqs = intent["requirements"]
    # Requirements merge across every use case; ordering controls only which named intent leads
    # capability prose and clarification.
    decision = dataclasses.replace(decision, use_cases=tuple(intent["use_cases"]),
                                   use_case_variants=dict(intent.get("use_case_variants") or {}))
    # Observation only: measure the legacy title/decomposer paths against the
    # canonical model-plus-registry interpretation before retiring them.  This
    # result is attached after response construction and never influences the
    # decision, requirements, retrieval, ranking, or authorization path.
    from src.app.services.workload_interpretation_shadow import observe_workload_interpretations

    workload_interpretation_shadow = observe_workload_interpretations(
        envelope.query,
        canonical_entities=decision.workload_entities,
        canonical_use_cases=decision.use_cases,
    )
    # review-8 #4 (accessory req-slot leak): a use-case/workload's device floors describe the
    # DEVICE, not an accessory bought FOR it. If the requested product is not a workload-host
    # device ('a mouse for gaming', 'a bag for my gaming laptop' route to accessory nodes), keep
    # ONLY the shopper's explicitly-stated requirements and drop the KB/game/software-derived
    # floors — which also keeps `decision.requirements` empty so the empty-node broad-retry (that
    # bled pharmacy into a mouse query) never fires for accessories.
    if not _is_workload_host_product(decision.requested_product_node):
        dropped = {k: v for k, v in resolved_reqs.items() if k not in stated_keys}
        if dropped:
            resolved_reqs = {k: v for k, v in resolved_reqs.items() if k in stated_keys}
            logger.info("dropped %d workload req(s) for non-host product %s: %s",
                        len(dropped), decision.requested_product_node, sorted(dropped))
    decision = dataclasses.replace(decision, requirements=resolved_reqs)
    # UNGROUNDED-WORKLOAD REROUTE (review-8 pharmacy-bleed, 2nd hole): the router only reroutes a
    # NAMED software/media node ('so-3-1') to a device host. But 'i want to play valorant at 144fps'
    # (no device word) makes the model return node=None, and resolve_intent STILL detects the game
    # and yields device floors. node=None + device requirements = an ungrounded device workload →
    # reroute to the store's declared workload host so retrieval is a real device leg, never the
    # broad catalog search that bled pharmacy. (Accessory queries had their floors dropped just
    # above → requirements empty → this never fires for them.)
    if decision.node_handle is None and decision.requirements:
        from src.app.services.recommendation_core.turn_router import _reroute_host_node
        host = _reroute_host_node(db, envelope, "run_on")
        if host:
            hn = get_node(host)
            decision = dataclasses.replace(
                decision, node_handle=host, node_path=(hn.full_path if hn else None),
                requested_product_node=host, relationship="run_on")
            logger.info("ungrounded-workload reroute -> host %s (reqs=%s)", host,
                        sorted(decision.requirements))
    # R9.1 CONTINUATION INHERITANCE (screenshot 30 — the budget-loss bug): a refinement turn
    # ('show me cheaper ones') restates neither the budget nor the specs, so they vanished and
    # the follow-up re-anchored to the whole catalog. On a CONTINUATION lane only (the same
    # lanes whose nodeless turns inherit prior_node — M3-C2), adopt the session's accepted
    # constraints ADOPT-IF-ABSENT: a budget/requirement the shopper states THIS turn always
    # wins; a fresh SEARCH never inherits (context-rot guard, ledger §8). Runs BEFORE
    # derive_plan so fit_check comes back for inherited requirements.
    budget_inherited = requirements_inherited = False
    # EXPLAIN is financially non-destructive: naming competing products in "why X rather
    # than Y?" is not authorization to discard an accepted budget.  A model-proposed
    # subject switch only releases prior constraints when the buyer explicitly resets or
    # switches context.  Fresh searches remain isolated by the lane guard below.
    explicit_context_reset = bool(_EXPLICIT_CONTEXT_RESET.search(envelope.query or ""))
    active_lane = str((envelope.session or {}).get("active_workflow_lane")
                      or (envelope.session or {}).get("prior_lane") or "").strip().upper()
    is_continuation = (
        decision.subject_action == "continue"
        or (decision.lane in ("FILTER", "COMPARE", "EXPLAIN")
            and decision.subject_action != "switch")
        or (decision.lane == "EXPLAIN" and not explicit_context_reset)
        or (decision.lane == "PROCUREMENT"
            and active_lane == "PROCUREMENT"
            and decision.subject_action != "switch")
    )
    if is_continuation:
        acc = (envelope.session or {}).get("accepted_constraints") or {}
        if envelope.budget_min_cents is None and envelope.budget_max_cents is None:
            bmin, bmax = acc.get("budget_min_cents"), acc.get("budget_max_cents")
            if bmin is not None or bmax is not None:
                envelope = dataclasses.replace(envelope, budget_min_cents=bmin,
                                               budget_max_cents=bmax)
                budget_inherited = True
        prior_reqs = acc.get("requirements") or {}
        if not decision.requirements and isinstance(prior_reqs, dict) and prior_reqs:
            decision = dataclasses.replace(decision, requirements=dict(prior_reqs))
            requirements_inherited = True
        # Quantity is consequential and has its own continuity boundary. Subject continuity is
        # not enough: a fresh SEARCH that the model mislabels as "continue" must not resurrect
        # an old 20-unit order. Carry an omitted quantity only inside a known current-order /
        # procurement workflow; descriptive product follow-ups do not need quantity arithmetic.
        if (decision.quantity is None and decision.subject_action == "continue"
                and (decision.procurement_context == "current_order"
                     or active_lane == "PROCUREMENT")
                and acc.get("quantity")):
            decision = dataclasses.replace(decision, quantity=int(acc["quantity"]))
        if (decision.total_budget_cents is None
                and _parsed_turn_budget is None
                and _explicit_turn_scope == "unknown"
                and acc.get("total_budget_cents")):
            decision = dataclasses.replace(decision, total_budget_cents=int(acc["total_budget_cents"]))
        # BRAND continuation (review-10 P0.6): inherit brand constraints when THIS turn didn't set
        # one ('show me cheaper ones' keeps the prior 'only Asus' / 'not Apple'); stated wins.
        if decision.brand_action != "clear" and decision.brand_filter is None and acc.get("brand_filter"):
            decision = dataclasses.replace(decision, brand_filter=str(acc["brand_filter"]))
        if decision.brand_action != "clear" and decision.exclude_brand is None and acc.get("exclude_brand"):
            decision = dataclasses.replace(decision, exclude_brand=str(acc["exclude_brand"]))
        if decision.brand_action != "clear" and decision.preferred_brand is None and acc.get("preferred_brand"):
            decision = dataclasses.replace(decision, preferred_brand=str(acc["preferred_brand"]))

    # quantity is MODEL-JUDGED now (decision.quantity, clamped in the router) — no count-in-fit hack;
    # the router also excludes `count` from requirements, so nothing pollutes fit/closest-match.
    requested_quantity = decision.quantity
    quantity_inherited = False
    if (
        requested_quantity is None
        and is_continuation
        and isinstance((envelope.session or {}).get("accepted_constraints"), dict)
    ):
        prior_quantity = (envelope.session or {})["accepted_constraints"].get("quantity")
        try:
            if prior_quantity is not None and 1 <= int(prior_quantity) <= 100_000:
                # Preserve the buyer-visible order context without promoting it
                # into this turn's decision/proposal. Fresh searches never enter
                # this branch; an explicit quantity still wins above.
                requested_quantity = int(prior_quantity)
                quantity_inherited = True
        except (TypeError, ValueError) as exc:
            logger.warning("ignored invalid inherited quantity: %s", exc)

    plan = derive_plan(decision)   # model plan refinement arrives with the plan-proposal leg
    from src.app.services.recommendation_core.research_planner import build_research_plan

    research_plan = build_research_plan(
        plan.semantic_proposal,
        external_research_authorized=bool(envelope.external_research_consent),
        clarification_answer=envelope.clarification_answer,
    )
    plan = dataclasses.replace(
        plan,
        external_research_authorized=bool(envelope.external_research_consent),
        research_plan=research_plan.model_dump(),
    )
    # An unresolved purpose cannot inherit quantity from a different, older commercial subject.
    if plan.needs_concept_resolution and quantity_inherited:
        requested_quantity = None
        quantity_inherited = False

    resp = CoreResponse(envelope=envelope, lane=decision.lane, grounding=grounding)
    from src.app.services.recommendation_core.research_routing import (
        assess_research_trigger_shadow,
    )

    # Observer only: this records the features needed to calibrate a future QPP
    # model. It cannot change the lane, authorize egress, or permit catalog results.
    research_trigger = assess_research_trigger_shadow(
        plan.semantic_proposal,
        semantic_authority_state=plan.semantic_authority_state,
        commercial_materiality=(1.0 if requested_quantity and requested_quantity > 1 else 0.0),
    )
    resp.extras["research_trigger_shadow"] = research_trigger.model_dump()
    resp.extras["research_plan"] = research_plan.model_dump()
    if workload_interpretation_shadow is not None:
        resp.extras["workload_interpretation_shadow"] = dict(workload_interpretation_shadow)
    continuity_pending = (
        envelope.session.get("pending_clarification")
        if isinstance(envelope.session.get("pending_clarification"), dict) else {}
    )
    continuity_semantic = (
        continuity_pending.get("semantic_context")
        if isinstance(continuity_pending.get("semantic_context"), dict) else {}
    )
    # An inspectable receipt, not chain-of-thought: this records which authoritative
    # server-held state reached the core before the model proposal was authorized.
    resp.extras["continuity_input"] = {
        "pending_present": bool(continuity_pending),
        "question_id": str(continuity_pending.get("question_id") or "") or None,
        "pending_state": str(continuity_pending.get("state") or "") or None,
        "catalog_authority": str(continuity_semantic.get("catalog_authority") or "") or None,
        "material_concept_count": sum(
            1 for item in (continuity_semantic.get("concepts") or [])
            if isinstance(item, dict) and bool(item.get("material"))
        ),
        "external_research_consent": bool(
            envelope.external_research_consent
            or continuity_pending.get("external_research_consent")
        ),
        "clarification_answer": dict(envelope.clarification_answer),
        "session_epoch_present": bool(envelope.session.get("session_epoch")),
    }
    resp.record_stage("route+intent", status="ok",
                      latency_ms=(time.perf_counter() - _t_route) * 1000.0,
                      won_message=False, source=decision.source)
    model_metrics = last_router_call_metrics()
    if decision.model_proposal or model_metrics.get("model"):
        resp.extras["llm_model"] = model_metrics.get("model") or active_router_model()
        resp.extras["model_invocation"] = {
            key: model_metrics.get(key)
            for key in (
                "provider", "model", "model_version", "prompt_version", "policy_version",
                "outcome", "wall_ms", "queue_ms",
            )
            if model_metrics.get(key) is not None
        }
    if decision.source == "fallback:model_unavailable":
        model_outcome = str(model_metrics.get("outcome") or "source_unavailable")
        typed_outcome = (
            "timed_out"
            if model_outcome in {"timeout", "queue_timeout"}
            else "source_unavailable"
        )
        resp.degraded = True
        resp.extras["router_outcome"] = {
            "status": typed_outcome,
            "source": decision.source,
            "provider_outcome": model_outcome,
            "late_results_accepted": False,
            "fallback_authority": "deterministic_only",
        }
    resp.extras["decision"] = decision.as_dict()
    resp.extras["secondary_lanes"] = list(decision.secondary_lanes)
    if requested_quantity is not None:
        resp.extras["requested_quantity"] = requested_quantity
        resp.extras["quantity_inherited"] = quantity_inherited
    resp.extras["plan"] = plan.as_dict()
    resp.extras["execution_budgets"] = {
        "acknowledgement_ms": 1000,
        "router": dict(router_contract),
        "research": {
            "per_lane_ms": int(os.getenv("RESEARCH_LANE_TIMEOUT_MS", "1800") or 1800),
            "total_ms": int(os.getenv("RESEARCH_TOTAL_TIMEOUT_MS", "2000") or 2000),
        },
        "narration": {
            "mode": str(os.getenv("RECOMMEND_NARRATION_MODE", "blocking") or "blocking"),
            "separate_background_pool": True,
        },
    }
    # the resolver's reasoning, surfaced for the 'Why Recommended' decision-trace tab
    resp.extras["intent"] = {"use_cases": intent["use_cases"],
                             "use_case_variants": intent.get("use_case_variants") or {},
                             "primary_use_case": intent.get("primary_use_case"),
                             "workload_use_cases": intent.get("workload_use_cases") or [],
                             "context_use_cases": intent.get("context_use_cases") or [],
                             "context_preferences": intent.get("context_preferences") or {},
                             "profiles": intent["profile_trace"],
                             "title_requirements": intent.get("title_requirements") or {},
                             "persona_hint": intent["persona_hint"],
                             # M2-B1: full-fidelity ranges + surfaced conflicts for the trace
                             "constraints": intent.get("constraints") or {},
                             "conflicts": intent.get("conflicts") or []}
    resp.extras["constraints_used"] = {
        "budget_min_cents": envelope.budget_min_cents,
        "budget_max_cents": envelope.budget_max_cents,
        "node_handle": decision.node_handle,
        "requirements": {k: [list(p) for p in v] for k, v in decision.requirements.items()},
        "operational_constraints": dict(decision.operational_constraints),
        "use_cases": intent["use_cases"],
        "use_case_variants": intent.get("use_case_variants") or {},
        "brands": [decision.brand_filter] if decision.brand_filter else [],
        "brand_excludes": [decision.exclude_brand] if decision.exclude_brand else [],
        "preferred_brands": [decision.preferred_brand] if decision.preferred_brand else [],
        "budget_cap_mode": decision.budget_cap_mode,
        "workload_entities": [list(item) for item in decision.workload_entities],
        # provenance (R9.1): the trace must say when this turn's constraints came from the
        # SESSION, not the message — and postflight persists what was USED, so a budget-less
        # follow-up refreshes the remembered budget instead of wiping it.
        "budget_inherited": budget_inherited,
        "requirements_inherited": requirements_inherited,
    }

    # A named workload is an obligation, not a hint.  The model may identify
    # unfamiliar software or games, but a generic profile cannot silently stand
    # in for current vendor requirements.  Stop before retrieval when no enrolled
    # provider resolved the entity; this preserves honesty without adding
    # title-specific orchestration rules.
    workload_trace = (
        (intent.get("title_requirements") or {}).get("external_workload_evidence")
        if isinstance(intent.get("title_requirements"), dict) else None
    )
    workload_items = list((workload_trace or {}).get("items") or [])
    unresolved_workloads = [
        dict(item) for item in workload_items
        if isinstance(item, dict) and str(item.get("status") or "") != "resolved"
    ]
    if decision.workload_entities and unresolved_workloads:
        names = [
            str(item.get("requested_name") or "").strip()
            for item in unresolved_workloads
            if str(item.get("requested_name") or "").strip()
        ]
        subject = ", ".join(names[:2]) or "the named workload"
        if envelope.external_research_consent:
            question_text = (
                f"I identified {subject}, but no enrolled authoritative provider returned "
                "current requirements. Provide an approved requirements document or the "
                "minimum hardware and compatibility target; I will not substitute a generic "
                "profile and claim it is qualified."
            )
            missing_slots = ["authoritative_workload_requirements"]
        else:
            question_text = (
                f"I identified {subject}. May I check enrolled official sources for its "
                "current hardware and compatibility requirements before recommending products?"
            )
            missing_slots = ["external_research_consent"]
        resp.extras["workload_authorization"] = {
            "status": "blocked",
            "reason": "named_workload_evidence_unresolved",
            "entities": [list(item) for item in decision.workload_entities],
            "evidence": unresolved_workloads,
            "state_prevented": [
                "catalog_qualification", "buyer_commitment", "supplier_rfq",
            ],
            "next_permitted_action": "resolve_workload_requirements",
        }
        question = {
            "id": "workload_requirements",
            "goal": "resolve_named_workload",
            "reason": "named_workload_evidence_unresolved",
            "missing_slots": missing_slots,
            "text": question_text,
            "options": [],
        }
        resp.clarify.append(question)
        resp.set_message(question_text, MsgPriority.BULK_SCOPE_CLARIFY)
        resp.record_stage(
            "workload_evidence:pre_catalog",
            status="clarify",
            won_message=True,
            reason=question["reason"],
        )
        return resp.finalize()

    # MIXED-TURN AUTHORITY. Explicit money/quantity/date/identity grammar is only a
    # conservative fallback; every recognized obligation is still passed through the
    # canonical case reducer. The reducer may identify an authorization boundary but never
    # grants it. This prevents a trailing "confirm" from leapfrogging a pending amendment.
    from src.app.services.conversation_case_state import reduce_case_obligations

    session_anchor = (
        envelope.session.get("case_anchor")
        if isinstance(envelope.session.get("case_anchor"), dict) else {}
    )
    accepted_case = (
        envelope.session.get("accepted_constraints")
        if isinstance(envelope.session.get("accepted_constraints"), dict) else {}
    )
    pending_case = (
        envelope.session.get("pending_clarification")
        if isinstance(envelope.session.get("pending_clarification"), dict) else {}
    )
    session_semantic = (
        envelope.session.get("semantic_resolution")
        if isinstance(envelope.session.get("semantic_resolution"), dict) else {}
    )
    pending_semantic = (
        pending_case.get("semantic_context")
        if isinstance(pending_case.get("semantic_context"), dict) else {}
    )
    # An active material blocker is newer and more restrictive than an older
    # accepted session snapshot.  Letting the latter win reopens product and
    # commercial authority while the buyer is still resolving the workload.
    prior_semantic = (
        pending_semantic
        if pending_semantic.get("catalog_authority") == "blocked"
        else session_semantic or pending_semantic
    )
    pending_commercial = (
        pending_case.get("commercial_context")
        if isinstance(pending_case.get("commercial_context"), dict) else {}
    )
    case_state = {
        **accepted_case,
        **session_anchor,
        "sku": (
            session_anchor.get("selected_sku")
            or session_anchor.get("sku")
            or accepted_case.get("exact_product_sku")
        ),
        # Current accepted state precedes this turn's proposal. Relative operations
        # must compute from 30, not mistake the delta 10 for an absolute quantity.
        "quantity": (
            session_anchor.get("quantity")
            or accepted_case.get("quantity")
            or pending_commercial.get("quantity")
            or requested_quantity
        ),
        "budget": (
            session_anchor.get("budget")
            or accepted_case.get("budget")
            or {
                "scope": "total" if pending_commercial.get("total_budget_cents") else None,
                "total_cents": pending_commercial.get("total_budget_cents"),
                "currency": pending_commercial.get("currency"),
            }
        ),
        "atp_snapshot": session_anchor.get("atp_snapshot") or accepted_case.get("atp_snapshot"),
    }
    catalog_authority = str(
        prior_semantic.get("catalog_authority")
        or session_anchor.get("catalog_authority")
        or ("permitted" if not prior_semantic else "blocked")
    )
    case_obligations = reduce_case_obligations(
        envelope.query,
        current_state=case_state,
        catalog_authority=catalog_authority,
        selected_sku_candidate=decision.exact_product_sku,
    )
    if case_obligations:
        resp.extras["case_obligations"] = list(case_obligations)
        resp.extras["conversation_case_context"] = {
            "prior_quantity": case_state.get("quantity"),
            "budget": case_state.get("budget"),
            "catalog_authority": catalog_authority,
            "selected_sku": case_state.get("sku"),
            "trace_lineage": pending_case.get("trace_id"),
        }
        blocked_commitment = next(
            (
                item for item in case_obligations
                if item.get("kind") == "buyer_commitment"
                and item.get("status") in {"blocked", "clarify"}
            ),
            None,
        )
        if blocked_commitment is not None:
            reason = str(blocked_commitment.get("reason") or "commitment_prerequisite_missing")
            question_text = {
                "selected_product_anchor_required": "Select one evidence-qualified product before confirming the order.",
                "versioned_atp_snapshot_required": "I need a current, versioned availability check before confirming this order.",
                "catalog_authority_blocked": "Resolve the material product requirements before selecting or confirming an order.",
                "prior_obligation_requires_confirmation": "Confirm the pending case amendment before confirming the order.",
            }.get(reason, "Resolve the missing commitment prerequisite before confirming the order.")
            resp.clarify.append({
                "id": "commitment_prerequisite",
                "goal": "authorize_buyer_commitment",
                "reason": reason,
                "missing_slots": [reason],
                "text": question_text,
                "options": [],
            })
            # A mixed ``choose + confirm`` turn adds a commitment blocker; it does
            # not replace the evidence problem that caused the blocker. Preserve
            # the exact concepts, questions, source coverage and next permitted
            # action from the sealed semantic case so Decision Trace can explain
            # *what* remains unresolved instead of collapsing to a generic message.
            prevented = list(prior_semantic.get("state_prevented") or [])
            for item in ("buyer_commitment", "allocation", "supplier_rfq", "purchase_order"):
                if item not in prevented:
                    prevented.append(item)
            prior_questions = [
                dict(item) for item in (prior_semantic.get("questions") or [])
                if isinstance(item, dict)
            ]
            resp.extras["semantic_resolution"] = {
                **prior_semantic,
                "outcome": "clarify",
                "catalog_authority": catalog_authority,
                "residual_route": str(blocked_commitment.get("residual_route") or "ASK"),
                "residual_reasons": list(dict.fromkeys([
                    *list(prior_semantic.get("residual_reasons") or []),
                    reason,
                ])),
                "questions": (
                    prior_questions
                    or [{"question_id": "commitment_prerequisite", "question": question_text}]
                ),
                "state_prevented": prevented,
                "next_permitted_action": str(
                    prior_semantic.get("next_permitted_action")
                    or "resolve_commitment_prerequisite"
                ),
                "case_obligations": list(case_obligations),
            }
            resp.set_message(question_text, MsgPriority.BULK_SCOPE_CLARIFY)
            resp.record_stage(
                "case_obligations:pre_commitment",
                status="clarify",
                won_message=True,
                reason=reason,
            )
            return resp.finalize()

    # SMALL LOOP, BEFORE RETRIEVAL: only material missing slots stop execution. Generic workload
    # refinement remains post-retrieval; an unresolved bulk budget scope changes the authorized
    # price ceiling and therefore must be answered before products are selected.
    from src.app.services.recommendation_core.gates import (
        evaluate_text_gates, material_pre_retrieval_clarify, slot_gap_clarify,
    )
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

    # GENERIC SEMANTIC AUTHORITY GATE.  The model can identify an unfamiliar or
    # ambiguous concept and propose questions, but cannot turn that proposal into
    # catalog fit.  Evidence collection is bounded and consent-aware; only fully
    # normalized, provenance-bearing claims can resolve a material concept.
    semantic_decision_for_alignment = None
    semantic_catalog_qualifications: list[dict[str, Any]] = []
    semantic_compiled_requirements: list[dict[str, Any]] = []
    if plan.needs_concept_resolution:
        from src.app.services.evidence_orchestrator import (
            EvidenceBudget,
            gather_evidence as gather_semantic_evidence,
        )
        from src.app.services.semantic_resolution import (
            approved_narration_evidence,
            normalize_concept_evidence,
            reduce_semantic_proposal,
            validate_semantic_proposal,
        )

        raw_semantic = {
            key: value for key, value in plan.semantic_proposal.items()
            if key not in ("validation", "reasons")
        }
        semantic_turn_query = (
            envelope.buyer_query or envelope.query
            if decision.clarification_relation in {"interrupt", "supersede"}
            else envelope.query
        )
        semantic_anchor = (
            str(raw_semantic.get("desired_outcome") or envelope.query)
            if raw_semantic.get("persisted_case_blocker")
            else semantic_turn_query
        )
        if decision.clarification_relation in {"interrupt", "supersede"}:
            raw_semantic["desired_outcome"] = semantic_turn_query
        raw_semantic.pop("persisted_case_blocker", None)
        raw_semantic.pop("state_prevented", None)
        validation = validate_semantic_proposal(raw_semantic, query=semantic_anchor)
        try:
            semantic_lane_ms = max(100, min(int(os.getenv("RESEARCH_LANE_TIMEOUT_MS", "1800") or 1800), 30_000))
            semantic_total_ms = max(100, min(int(os.getenv("RESEARCH_TOTAL_TIMEOUT_MS", "2000") or 2000), 60_000))
        except (TypeError, ValueError):
            semantic_lane_ms, semantic_total_ms = 1800, 2000
        evidence_bundle = gather_semantic_evidence(
            plan,
            query=semantic_turn_query,
            uid=envelope.uid,
            tenant_id=envelope.tenant_id,
            web_consent=envelope.external_research_consent,
            evidence_budget=EvidenceBudget(
                per_lane_ms=semantic_lane_ms,
                total_ms=semantic_total_ms,
                max_cost_units=3,
            ),
        )
        normalized_rows = []
        concept_leg = (evidence_bundle.get("legs") or {}).get("concept_resolution") or {}
        concept_data = concept_leg.get("data") or {}
        if isinstance(concept_data.get("normalized_evidence"), list):
            normalized_rows = concept_data["normalized_evidence"]
        normalized = normalize_concept_evidence(normalized_rows)
        semantic_decision = reduce_semantic_proposal(
            validation,
            evidence=normalized,
            research_attempted=True,
            research_status=str(concept_data.get("status") or ""),
        )
        semantic_decision_for_alignment = semantic_decision
        from src.app.services.recommendation_core.requirement_compiler import (
            compile_authoritative_requirements,
        )

        compilation = compile_authoritative_requirements(
            item for item in list(concept_data.get("claims") or [])
            if isinstance(item, dict)
        )
        semantic_compiled_requirements = [
            item.model_dump() for item in compilation.requirements
        ]
        resp.extras["semantic_requirement_compilation"] = {
            "status": "accepted" if semantic_compiled_requirements else "blocked",
            "compiled_requirements": semantic_compiled_requirements,
            "rejected_claims": [dict(item) for item in compilation.rejections],
            "catalog_authority_granted": bool(semantic_compiled_requirements),
            "commercial_authority_granted": False,
        }
        semantic_catalog_qualifications = [
            dict(item) for item in (concept_data.get("catalog_qualifications") or [])
            if isinstance(item, dict)
        ][:100]
        # Provider-qualified identities are bounded retrieval candidates, not a
        # buyer selection.  Without this join, ordinary top-N category retrieval
        # can omit a qualified (often higher-cost) SKU and the alignment stage
        # incorrectly reports no match even though approved evidence named one.
        resp.extras["catalog_qualification_candidates"] = [
            str(item["sku"])
            for item in semantic_catalog_qualifications
            if item.get("sku")
        ]
        resp.extras["semantic_resolution"] = semantic_decision.as_dict()
        resp.extras["semantic_evidence"] = evidence_bundle
        resp.extras["approved_narration_evidence"] = list(
            approved_narration_evidence(normalized)
        )
        prior_case_anchor = (
            envelope.session.get("case_anchor")
            if isinstance(envelope.session.get("case_anchor"), dict)
            else {}
        )
        semantic_case_id = str(prior_case_anchor.get("case_id") or "").strip()
        if not semantic_case_id:
            session_epoch = str(envelope.session.get("session_epoch") or "current")
            semantic_case_id = "semantic-" + hashlib.sha256(
                f"{envelope.tenant_id}|{envelope.uid}|{session_epoch}".encode("utf-8")
            ).hexdigest()[:24]
        # Persist an inspectable semantic revision. This stores no chain-of-thought:
        # model confidence, evidence support, deterministic constraints and authority
        # remain separate. Persistence failure is visible in the trace and never
        # silently grants catalog authority.
        try:
            from src.app.services.conversation_case_state import ensure_case_state
            from src.app.services.semantic_belief_state import persist_semantic_belief

            session_epoch = str(envelope.session.get("session_epoch") or "current")
            ensure_case_state(
                db,
                tenant_id=envelope.tenant_id,
                case_id=semantic_case_id,
                session_epoch=session_epoch,
                subject_ref=hashlib.sha256(
                    f"{envelope.tenant_id}|{envelope.uid}".encode("utf-8")
                ).hexdigest(),
                authoritative_anchor={
                    "kind": "semantic_qualification",
                    "quantity": requested_quantity,
                    "budget": {
                        "scope": decision.budget_scope,
                        "total_cents": decision.total_budget_cents,
                        "currency": envelope.currency,
                    },
                },
            )
            belief_result = persist_semantic_belief(
                db,
                tenant_id=envelope.tenant_id,
                case_id=semantic_case_id,
                session_epoch=session_epoch,
                semantic_decision=semantic_decision.as_dict(),
                accepted_evidence=[item.as_dict() for item in normalized],
                compiled_requirements=semantic_compiled_requirements,
                trace_id=envelope.trace_id,
            )
            resp.extras["semantic_belief_state"] = belief_result
        except Exception as exc:
            logger.warning(
                "semantic belief persistence failed for trace %s: %s",
                envelope.trace_id,
                type(exc).__name__,
            )
            resp.extras["semantic_belief_state"] = {
                "status": "persistence_failed",
                "persisted": False,
                "error_type": type(exc).__name__,
            }
        if semantic_decision.catalog_authority != "permitted":
            # A model can echo a quantity from prior prompt context even when the buyer
            # has switched to a new unresolved subject. Consequential commercial state
            # requires buyer-authored evidence in this turn; bounded model output alone
            # is not sufficient. Explicit quantities remain visible, while relative
            # amendments stay in case_obligations until confirmation.
            if not decision.quantity_explicit:
                resp.extras.pop("requested_quantity", None)
                resp.extras.pop("quantity_inherited", None)
            # Typed clients must clear any prior slate without depending on the
            # legacy adapter to infer this from an empty product list.
            resp.extras["slate_disposition"] = "clear"
            resp.extras["case_anchor"] = {
                **prior_case_anchor,
                "case_id": semantic_case_id,
                "kind": "semantic_qualification",
                "selected_sku": prior_case_anchor.get("selected_sku"),
                "catalog_authority": "blocked",
            }
            from src.app.services.recommendation_core.clarification_policy import (
                select_semantic_clarification,
            )

            question = select_semantic_clarification(
                research_status=str(concept_data.get("status") or ""),
                proposed_questions=list(semantic_decision.questions or ()),
                material_unknowns=list(semantic_decision.material_unknowns or ()),
                workload_hypotheses=list(semantic_decision.workload_hypotheses or ()),
                commercial_materiality=(
                    1.0 if requested_quantity and requested_quantity > 1 else 0.0
                ),
            )
            resp.clarify.append(question)
            resp.set_message(question["text"], MsgPriority.BULK_SCOPE_CLARIFY)
            resp.record_stage(
                "semantic_resolution:pre_catalog",
                status=semantic_decision.outcome,
                won_message=True,
                reason=question["reason"],
            )
            return resp.finalize()
        if compilation.requirements:
            merged_requirements = {
                key: list(predicates)
                for key, predicates in decision.requirements.items()
            }
            for requirement in compilation.requirements:
                predicate = (requirement.operator, requirement.value)
                predicates = merged_requirements.setdefault(requirement.attribute_key, [])
                if predicate not in predicates:
                    predicates.append(predicate)
            decision = dataclasses.replace(decision, requirements=merged_requirements)
            # Evidence changed the executable fit contract, so derive the plan again.
            # Preserve the already-authorized bounded research plan; no second model or
            # provider call is introduced here.
            plan = dataclasses.replace(
                derive_plan(decision),
                external_research_authorized=bool(envelope.external_research_consent),
                research_plan=research_plan.model_dump(),
            )
            resp.extras["decision"] = decision.as_dict()
            resp.extras["plan"] = plan.as_dict()
            resp.extras["constraints_used"]["requirements"] = {
                key: [list(predicate) for predicate in predicates]
                for key, predicates in decision.requirements.items()
            }
    if decision.product_type_options:
        choices = []
        for handle in decision.product_type_options:
            option_node = get_node(handle)
            if option_node is not None:
                choices.append({"id": handle, "label": option_node.name})
        question = {
            "id": "product_type",
            "goal": "resolve_product_type",
            "reason": "missing_material_product_type",
            "missing_slots": ["product_type"],
            "text": "Which product type do you need for this workload?",
            "options": choices,
        }
        resp.clarify.append(question)
        resp.set_message(question["text"], MsgPriority.BULK_SCOPE_CLARIFY)
        resp.record_stage("clarify:pre_retrieval", status="clarify", won_message=True,
                          reason=question["reason"])
        return resp.finalize()
    material_question = material_pre_retrieval_clarify(
        quantity=decision.quantity,
        budget_known=(decision.total_budget_cents is not None
                      or envelope.budget_max_cents is not None
                      or envelope.budget_min_cents is not None),
        budget_scope=decision.budget_scope,
    )
    if material_question and not (
            decision.lane == "OFF_CATALOG" and decision.refusal_granted):
        resp.clarify.append(material_question)
        resp.set_message(material_question["text"], MsgPriority.BULK_SCOPE_CLARIFY)
        resp.record_stage("clarify:pre_retrieval", status="clarify", won_message=True,
                          reason=material_question["reason"])
        return resp.finalize()

    # plan executors are the turn's MAIN work (retrieve / fit / compare / handoff); time the whole
    # planned sequence as one 'plan' breadcrumb, with the retrieval count the evidence leg recorded.
    _t_plan = time.perf_counter()
    _prio_before = resp._msg_priority
    for step in plan.steps:
        _EXECUTORS[step](db, envelope, decision, resp, limit)
    resp.record_stage("plan:" + "+".join(plan.steps), status="ok",
                      latency_ms=(time.perf_counter() - _t_plan) * 1000.0,
                      retrieval_count=int((resp.extras.get("evidence") or {}).get("count") or 0),
                      won_message=resp._msg_priority > _prio_before)

    # Resolving a concept permits catalog alignment; it does not itself prove
    # that any SKU is suitable. A provider can supply an explicit SKU qualification,
    # or accepted claims can compile into registry predicates and the ordinary fit
    # evaluator can qualify a product. Similarity and product prose stay unverified.
    if semantic_decision_for_alignment is not None:
        from src.app.services.semantic_resolution import align_catalog

        qualification_by_sku = {
            str(item.get("sku")): str(item.get("alignment_status") or "unverified")
            for item in semantic_catalog_qualifications
            if item.get("sku")
        }
        alignment = align_catalog(
            semantic_decision_for_alignment,
            [
                {
                    "sku": product.sku,
                    "alignment_status": qualification_by_sku.get(
                        product.sku,
                        "qualified"
                        if (
                            semantic_compiled_requirements
                            and (product.fit or {}).get("overall") == "meets"
                        )
                        else "unverified",
                    ),
                }
                for product in resp.products
            ],
        )
        resp.extras["catalog_alignment"] = alignment.as_dict()
        allowed_skus = set(alignment.exact + alignment.qualified + alignment.alternatives)
        resp.products = [product for product in resp.products if product.sku in allowed_skus]
        if alignment.status == "no_exact_catalog_match":
            resp.extras["supplier_enquiry_option"] = {
                "status": "available_after_buyer_commitment",
                "auto_sent": False,
                "evidence_refs": [
                    row.get("citation_id")
                    for row in (resp.extras.get("approved_narration_evidence") or [])
                    if row.get("citation_id")
                ],
            }
            if alignment.alternatives:
                resp.set_message(
                    "No exact evidence-qualified catalog match was found. These are qualified "
                    "alternatives; supplier enquiry remains available after buyer commitment.",
                    MsgPriority.CAPABILITY_STATEMENT,
                )
            else:
                resp.set_message(
                    "No exact or qualified catalog match is currently supported by approved "
                    "evidence. I can preserve the requirements for a supplier enquiry after "
                    "buyer commitment.",
                    MsgPriority.CAPABILITY_STATEMENT,
                )

    # Closed, model-interpreted scope with a deterministic authorization clamp in the router.
    # This is intentionally generic: the core does not learn pizza, restaurants, plumbers, or
    # other domain phrases. It explains the platform boundary without pretending a catalog miss.
    if decision.request_scope == "service_or_place" and not resp.products:
        resp.extras["unsupported_scope"] = {
            "kind": "service_or_place",
            "can_help_with": "products_sold_by_store",
        }
        resp.set_message(
            "I can help compare and source products sold by this store, but I can't recommend "
            "local services or places. Try a local directory or map service for that request.",
            MsgPriority.REFUSAL,
        )

    # gates: prefer the SHARED commerce guard's verdict (run once at the facade ingress) —
    # the core does NOT own a second security regex (GPT-5.6 #10). The thin evaluate_text_gates
    # is the NO-FACADE fallback only (offline replay / direct tests).
    # M2-B1: a CONFLICTED requirement ('nothing over 8GB' stated vs a use-case floor of 16) is
    # the SHOPPER'S call — surface the clarify; never silently pick a side.
    if intent.get("conflicts") and not resp.off_catalog and not resp.clarify:
        c0 = intent["conflicts"][0]
        resp.clarify.append({
            "id": f"conflict_{c0['key']}",
            "text": (f"Quick check — part of your request needs {c0['key']} of at least "
                     f"{c0['lower']:g}, but you also asked for at most {c0['upper']:g}. "
                     f"Which matters more?"),
            "goal": "resolve_requirement_conflict",
            "options": [
                {"id": "keep_floor", "label": f"At least {c0['lower']:g} (performance)"},
                {"id": "keep_ceiling", "label": f"At most {c0['upper']:g} (my stated limit)"},
            ]})

    # POST-RETRIEVAL STAGES (P0.5): each is guarded + timed + telemetry-recorded by _run_stage —
    # a stage failure is logged and skipped, never fatal (the products already stand on their own;
    # the whole core is gated by RECOMMEND_CORE_MODE at the facade, off in prod until flip). Message
    # priority is EXPLICIT (MsgPriority via set_message), so this order sets EXECUTION order, not
    # which sentence the buyer reads — reordering can no longer silently steal the message.
    #   capability-budget (1a) — floor / within-budget confirm / below-budget tradeoff, after the
    #     conflict clarify (stated-requirement conflict outranks) and before slot-gap.
    #   shelf (1b)           — partition ranked cards into the 3-band panel; reads the capability banner.
    #   variant-clarify (1c) — one question when a variant materially moves the floor; else assumption.
    #   complement-offer (1d.4) — declared complement → bundle-upsell if stocked, else source-it RFQ.
    #   bulk-economics (1f)  — 'N units, $T total' → ÷units viability + tradeoff menu.
    _run_stage(resp, "capability_budget",
               lambda: _apply_capability_budget(db, envelope, decision, resp, limit))
    _run_stage(resp, "shelf", lambda: _build_shelf(db, envelope, decision, resp, limit))
    _run_stage(resp, "variant_clarify",
               lambda: _maybe_variant_clarify(envelope, decision, resp))
    _run_stage(resp, "complement_offer",
               lambda: _maybe_complement_offer(db, envelope, decision, resp))
    _run_stage(resp, "bulk_economics",
               lambda: _maybe_bulk_economics(db, envelope, decision, resp))
    _run_stage(resp, "fulfillment_preview",
               lambda: _maybe_fulfillment_preview(envelope, decision, resp))
    _run_stage(resp, "secondary_explanation",
               lambda: _apply_secondary_explanation(decision, resp))

    # clarify (census bucket 2): v1's NQE equivalent as deterministic slot-gap UX policy
    if not resp.off_catalog and not resp.clarify:
        q = slot_gap_clarify(
            has_products=bool(resp.products),
            budget_known=envelope.budget_max_cents is not None or envelope.budget_min_cents is not None,
            has_requirements=bool(decision.requirements),
            has_use_case=bool(decision.use_cases))
        if q:
            resp.clarify.append(q)
    return resp.finalize()


# ── the deterministic tool executors (the plan vocabulary's other half) ───────

def _preferred_values(resp: CoreResponse) -> Optional[Dict[str, float]]:
    """The KB's RECOMMENDED values out of the resolver's full-fidelity constraints (review-9 #3
    closes review-6 #20): {key: preferred} for the ranker's soft nearness stage. None when no
    constraint carries one — ordering is then byte-identical to the pre-preference ranker."""
    try:
        cons = (resp.extras.get("intent") or {}).get("constraints") or {}
        out = {k: float(c["preferred"]) for k, c in cons.items()
               if isinstance(c, dict) and c.get("preferred") is not None}
        return out or None
    except Exception:
        return None


def _capability_phrase(decision: TurnDecision) -> str:
    """A short human name for the asserted capability — the use-case the model named
    ('drawing', 'gaming') if there is one, else the resolved requirement keys. Used only for
    buyer-facing prose (the floor/tradeoff message), never for a decision."""
    ucs = list(getattr(decision, "use_cases", None) or [])
    if ucs:
        return str(ucs[0]).replace("_", " ")
    keys = list((decision.requirements or {}).keys())
    return ", ".join(k.replace("_", " ") for k in keys[:3]) or "your use case"


def _capability_scope_nodes(decision: TurnDecision) -> list:
    """The node(s) to compute the capability FLOOR over. When the routed product is a workload
    HOST (a device), use the store's DECLARED device host union (capability_host_nodes[run_on] =
    [Laptops, Gaming Laptops]) so the floor spans the whole device FAMILY, not just the routed leaf
    — a GPU/creative intent routed to 'Laptops' must still see 'Gaming Laptops' (else the floor
    inflates: $4894 vs the real $1919). DATA-DRIVEN (the profile declares the union); no hardcoded
    'GPU → Gaming Laptops' rule. Accessories (non-host) stay scoped to their own node."""
    node = decision.node_handle
    if not node:
        return []
    if not _is_workload_host_product(node):
        return [node]
    try:
        from src.app.platform.store_profile import profile_slot
        hosts = (profile_slot("capability_host_nodes", default={}) or {}).get("run_on") or []
        return list(dict.fromkeys([node] + [str(h) for h in hosts]))
    except Exception as exc:
        logger.debug("capability host union lookup failed: %s", repr(exc)[:100])
        return [node]


def _gather_scope_variants(db, free_env: TurnEnvelope, decision: TurnDecision, limit: int) -> list:
    """Union of variants across the capability-scope nodes (device host family), dedup by sku."""
    n = max(limit * 20, 200)
    variants, seen = [], set()
    for node in _capability_scope_nodes(decision):
        b = gather_evidence(db, free_env, node_handle=node, limit=n)
        if b.status == "ok":
            for v in b.variants:
                if v.sku not in seen:
                    seen.add(v.sku)
                    variants.append(v)
    return variants


def _budget_free_cards(db, envelope: TurnEnvelope, decision: TurnDecision, limit: int) -> list:
    """Ranked cards for the routed node IGNORING budget — the above-budget stretch/premium set is
    otherwise invisible (gather_evidence hard-filters budget at the evidence edge). This is what
    lets 'nothing at $900 — the real floor is $1199' be honest instead of an empty grid, and what
    fills the shelf's stretch band. Cold path (only when nothing in-budget meets). Generous
    candidate cap because the slate is sku-ordered and attributes aren't in SQL (a paged MIN()
    query waits on Phase 4 typed price columns). [] on empty/error."""
    import dataclasses
    free_env = dataclasses.replace(envelope, budget_min_cents=None, budget_max_cents=None)
    n = max(limit * 20, 200)
    variants = _gather_scope_variants(db, free_env, decision, limit)   # device host FAMILY, not just the leaf
    if not variants:
        return []
    # Currency is an authorization boundary on every retrieval leg, including this auxiliary
    # budget-free probe. A probe must never reintroduce numerically cheap USD rows into an AUD
    # slate merely because the primary evidence path filtered them correctly.
    requested_currency = str(envelope.currency or "").strip().upper()
    variants = [v for v in variants
                if str(v.currency or "").strip().upper() == requested_currency]
    if not variants:
        return []
    # HONESTY (review finding #1): a HARD brand filter must not leak off-brand products into the
    # floor/stretch — 'only Dell, $900' must never quote a Lenovo as 'the cheapest that meets'.
    bf = getattr(decision, "brand_filter", None)
    if bf:
        blf = str(bf).strip().lower()
        variants = [v for v in variants if (v.brand or "").strip().lower() == blf]
        if not variants:
            return []
    xb = getattr(decision, "exclude_brand", None)
    if xb:
        xbl = str(xb).strip().lower()
        variants = [v for v in variants if (v.brand or "").strip().lower() != xbl]
    cards, _ = build_cards(variants, decision.requirements or None, limit=n)
    return cards


def _inferred_subject_from_variants(variants: list) -> Optional[str]:
    """Return the deepest shared, non-root taxonomy subject for an authorized slate.

    Text fallback can retrieve a coherent slate even when the router supplies no node. Persisting
    that bounded catalog subject lets later FILTER/COMPARE turns refine the slate instead of
    text-searching a fragment such as "exclude Apple". A vertical root is deliberately rejected:
    it is too broad to be useful continuation evidence.
    """
    from src.app.services.taxonomy_registry import ancestors, get_node

    chains = []
    for variant in variants:
        handle = str(getattr(variant, "taxonomy_node_id", None) or "").strip()
        node = get_node(handle)
        if node is None:
            continue
        chains.append({node.handle, *(ancestor.handle for ancestor in ancestors(node.handle))})
    if not chains:
        return None
    shared = set.intersection(*chains)
    candidates = [get_node(handle) for handle in shared]
    specific = [node for node in candidates if node is not None and node.depth >= 1]
    return max(specific, key=lambda node: (node.depth, node.handle)).handle if specific else None


def _budget_free_floor(db, envelope: TurnEnvelope, decision: TurnDecision,
                       limit: int) -> Optional[int]:
    """The capability floor IGNORING budget — cheapest node product that MEETS, even above the
    shopper's ceiling (the honest 'the real floor is $1199')."""
    prices = [c.price_cents for c in _budget_free_cards(db, envelope, decision, limit)
              if c.price_cents is not None and (c.fit or {}).get("overall") == "meets"]
    return min(prices) if prices else None


def _apply_capability_budget(db, envelope: TurnEnvelope, decision: TurnDecision,
                             resp: CoreResponse, limit: int) -> None:
    """Phase 1a — the budget × capability 'smart moment'. Using the capability FLOOR (cheapest
    catalog product that MEETS the resolved requirements — DERIVED, never a stored number),
    branch on the shopper's budget: state the floor (no budget), confirm within budget, or offer
    an honest tradeoff when budget < floor (never a silent empty/mismatch). No-op unless a real
    capability was asserted on a product-search lane and the turn isn't degraded/off-catalog.
    Reads decision.requirements (the authoritative merged predicates)."""
    if decision.lane not in ("SEARCH", "FILTER", "PROCUREMENT"):
        return
    if not decision.requirements or resp.off_catalog or resp.degraded:
        return
    fs = resp.fit_summary or {}
    bmax = envelope.budget_max_cents
    meets_in_budget = int(fs.get("meets") or 0)
    floor = fs.get("capability_floor_cents")     # cheapest MEETS within the retrieved (budget) set
    probed = False
    # budget < floor case: nothing in-budget meets, but a ceiling was set → probe the true floor
    # ONCE and memoize the cards on resp so the shelf reuses them (review finding #2: no 2nd retrieval).
    if floor is None and bmax is not None and decision.node_handle:
        bf_cards = _budget_free_cards(db, envelope, decision, limit)
        resp._bf_cards = bf_cards
        meets_prices = [c.price_cents for c in bf_cards if c.price_cents is not None
                        and (c.fit or {}).get("overall") == "meets"]
        floor = min(meets_prices) if meets_prices else None
        probed = True
        # The broader host-scope probe may recover a valid product that the initial leaf
        # retrieval missed. If it is still inside the authorized cap, it belongs in the primary
        # slate; do not merely quote its floor while showing inferior failing products.
        bmin = envelope.budget_min_cents
        recovered = [c for c in bf_cards
                     if c.price_cents is not None
                     and (bmin is None or c.price_cents >= bmin)
                     and c.price_cents <= bmax
                     and (c.fit or {}).get("overall") == "meets"]
        if recovered:
            existing = {c.sku for c in recovered}
            original_cards = [
                c for c in resp.products
                if c.sku not in existing
            ]
            resp.products = (recovered + original_cards)[:limit]
            meets_in_budget = sum(
                1 for c in resp.products
                if (c.fit or {}).get("overall") == "meets"
            )
            fs["meets"] = sum(1 for c in resp.products
                              if (c.fit or {}).get("overall") == "meets")
            fs["fails"] = sum(1 for c in resp.products
                              if (c.fit or {}).get("overall") == "fails")

    cap: Dict[str, Any] = {"floor_cents": floor, "budget_max_cents": bmax,
                           "meets_in_budget": meets_in_budget, "probed_budget_free": probed,
                           "requirements": fs.get("requirements") or {}}
    phrase = _capability_phrase(decision)

    if floor is None:
        # nothing in the catalog meets — a genuine closest-match (already messaged by retrieve)
        cap["verdict"] = "no_catalog_match"
    elif bmax is None:
        cap["verdict"] = "floor_stated"
        shown_meets = [c.price_cents for c in resp.products if c.price_cents is not None
                       and (c.fit or {}).get("overall") == "meets"]
        top = max(shown_meets, default=floor)
        if top > floor:
            resp.set_message((f"These all handle {phrase} — they start at ${floor / 100:,.0f} "
                              f"and go up to ${top / 100:,.0f} for more headroom."),
                             MsgPriority.CAPABILITY_STATEMENT)
        else:
            resp.set_message(f"These all handle {phrase}, starting at ${floor / 100:,.0f}.",
                             MsgPriority.CAPABILITY_STATEMENT)
    elif floor <= bmax:
        cap["verdict"] = "within_budget"
        # fill-only: a lane-base message (closest-match / compare) outranks this confirm — the
        # CAPABILITY_WITHIN_BUDGET priority (< LANE_BASE) reproduces the old `if not message` guard.
        resp.set_message((f"The best fit for {phrase} starts at ${floor / 100:,.0f}, within "
                          f"your ${bmax / 100:,.0f} budget."), MsgPriority.CAPABILITY_WITHIN_BUDGET)
    else:
        cap["verdict"] = "below_budget"
        if resp.products:
            resp.set_message((f"Nothing at ${bmax / 100:,.0f} fully meets what {phrase} needs — the "
                              f"cheapest that does is ${floor / 100:,.0f}. Showing the closest in "
                              f"your budget below."), MsgPriority.CAPABILITY_STATEMENT)
        else:
            resp.set_message((f"I don't have anything at ${bmax / 100:,.0f} that meets what {phrase} "
                              f"needs — the cheapest that does is ${floor / 100:,.0f}."),
                             MsgPriority.CAPABILITY_STATEMENT)
        # one structured tradeoff, only if no higher-priority clarify already claimed the slot
        if not resp.clarify:
            resp.clarify.append({
                "id": "capability_budget_tradeoff",
                "text": (f"Your budget is ${bmax / 100:,.0f}, but the floor for {phrase} is "
                         f"${floor / 100:,.0f}. How would you like to proceed?"),
                "goal": "resolve_budget_capability_gap",
                "options": [
                    {"id": "stretch", "label": f"Stretch to ${floor / 100:,.0f} for the real fit"},
                    {"id": "relax", "label": "Relax a requirement (I'll show what changes)"},
                    {"id": "closest", "label": "Just show the closest in my budget"},
                ]})
    resp.extras["capability"] = cap


def _band(band_id: str, label: str, basis: str, cards: list) -> Dict[str, Any]:
    """One shelf band, self-describing so the frontend renders it blind: skus + full card dicts
    (each carries its honest fit verdict chip) + the reason it exists."""
    return {"id": band_id, "label": label, "basis": basis,
            "skus": [c.sku for c in cards], "cards": [c.as_dict() for c in cards]}


def _build_shelf(db, envelope: TurnEnvelope, decision: TurnDecision,
                 resp: CoreResponse, limit: int) -> None:
    """Phase 1b — the 3-band right-side shelf: a PARTITION of the ranked cards (no new model call,
    vertical-blind), the presentation contract the panel renders.
      band 1 best_fit  — the top-3 answer to intent+budget (meets-in-budget, else the closest,
                         labeled honestly);
      band 2 stretch / more_capable — meets NOT in band 1. below_budget → the above-budget meets
                         to stretch to (cheapest = the floor); within/no-budget → 'more capable' =
                         capability HEADROOM (exceeds a requirement), never merely pricier;
      band 3 preference — a stated brand/variant preference, OMITTED when none was expressed.
    Adaptive (empty bands dropped), deduped (a product in exactly one band, priority 1>2>3),
    every card keeps its honest fit verdict. Runs after the capability banner; never raises."""
    if decision.lane not in ("SEARCH", "FILTER", "PROCUREMENT"):
        return
    if not decision.requirements or resp.off_catalog or resp.degraded:
        return
    cap = resp.extras.get("capability") or {}
    verdict = cap.get("verdict")
    floor = cap.get("floor_cents")
    bmax = envelope.budget_max_cents
    meets = lambda c: (c.fit or {}).get("overall") == "meets"          # noqa: E731
    margin = lambda c: len((c.fit or {}).get("exceeds") or [])         # noqa: E731

    in_budget = list(resp.products)          # already ranked; budget-filtered (or full if no bmax)
    above_budget: list = []
    if verdict == "below_budget" and decision.node_handle:
        # the stretch story lives ABOVE the ceiling — REUSE the budget-free set the floor probe
        # already fetched (memoized on resp); only fetch if it isn't there (review finding #2).
        bf_cards = getattr(resp, "_bf_cards", None)
        if bf_cards is None:
            bf_cards = _budget_free_cards(db, envelope, decision, limit)
        in_ids = {c.sku for c in in_budget}
        above_budget = [c for c in bf_cards
                        if c.sku not in in_ids and (c.price_cents or 0) > (bmax or 0)]
    universe = in_budget + above_budget
    used: set = set()
    bands: list = []

    # band 1 — best fit for intent+budget (meets-in-budget, else the honest closest)
    meets_in = [c for c in in_budget if meets(c)]
    band1 = (meets_in or in_budget)[:3]
    used.update(c.sku for c in band1)
    if band1:
        if meets_in:
            bands.append(_band("best_fit", "Best fit for you", "intent+budget", band1))
        else:
            bands.append(_band("closest_fit", "Closest within budget - requirements not met",
                               "closest_noncompliant", band1))

    # band 2 — stretch (below budget) OR more-capable headroom (within / no budget)
    rest_meets = [c for c in universe if c.sku not in used and meets(c)]
    if verdict == "below_budget":
        rest_meets.sort(key=lambda c: (c.price_cents or 0))            # cheapest stretch = the floor
        band2 = rest_meets[:3]
        label = (f"Meets your needs — stretch from ${floor / 100:,.0f}"
                 if floor else "Meets your needs (stretch)")
        band2_id, basis = "stretch", "meets_stretch"
    else:
        headroom = [c for c in rest_meets if margin(c) > 0]            # HEADROOM, not just pricier
        headroom.sort(key=lambda c: (-margin(c), c.price_cents or 0))
        band2 = headroom[:3]
        band2_id, label, basis = "more_capable", "More capable", "capability_headroom"
    used.update(c.sku for c in band2)
    if band2:
        bands.append(_band(band2_id, label, basis, band2))

    # band 3 — brand/variant/spec preference (only when a signal was expressed)
    pref = getattr(decision, "preferred_brand", None) or getattr(decision, "brand_filter", None)
    if pref:
        p = str(pref).strip().lower()
        pool = [c for c in universe if c.sku not in used and (c.brand or "").strip().lower() == p]
        pool.sort(key=lambda c: (0 if meets(c) else 1, c.price_cents or 0))
        band3 = pool[:3]
        used.update(c.sku for c in band3)
        if band3:
            bands.append(_band("preference", f"If you prefer {str(pref).strip().title()}",
                               f"brand:{p}", band3))

    resp.extras["shelf"] = {
        "banner": {"kind": verdict or ("within_budget" if bmax else "floor_stated"),
                   "text": resp.message, "floor_cents": floor, "budget_max_cents": bmax},
        "bands": bands,
    }


_VERTICAL_BY_ROOT = {"el": "electronics", "hg": "home", "fr": "furniture", "ap": "appliances"}
_VARIANT_SPREAD_MIN = 0.20            # material relative low-end spread across a use-case's variants
_VARIANT_SPREAD_MIN_DOLLARS = 250     # …or this absolute low-end gap (band hints are DOLLARS)


def _vertical_name(node_handle: Optional[str]) -> Optional[str]:
    """Registry vertical name (electronics/home/…) for a node's vertical root (el → electronics).
    Mirrors the registry files' host_nodes; None when unmapped (no clarify rather than a guess)."""
    return _VERTICAL_BY_ROOT.get(_vertical_root(node_handle) or "")


def _maybe_variant_clarify(envelope: TurnEnvelope, decision: TurnDecision,
                           resp: CoreResponse) -> None:
    """Phase 1c — ONE variant question, only when it materially moves the floor AND the shopper
    hasn't anchored it. A use-case whose variants' band hints (from use_case_registry) spread
    materially is ambiguous: with NO budget we ask (options labeled by their band); with a budget
    the capability-floor logic already picks the tier, so we state an assumption instead of nagging;
    if the query already names a variant we pin it silently. Content-advisory (a minor requesting
    mature-game specs) surfaces as a note, NEVER a block. Additive — reads the smart KB for the
    ASK decision only; the recommendation's requirements still come from the live resolver."""
    if decision.lane != "SEARCH" or resp.clarify or resp.off_catalog or resp.degraded:
        return
    vertical = _vertical_name(decision.node_handle)
    if not vertical:
        return
    import re
    from src.app.services import use_case_registry as R
    qtokens = set(re.findall(r"[a-z0-9]+", (envelope.query or "").lower()))
    for uc in list(getattr(decision, "use_cases", None) or []):
        adv = R.content_advisory(vertical, uc)
        if adv:
            resp.extras.setdefault("advisories", []).append(adv)      # surface, never block
        named = R.list_variants(vertical, uc)
        if not named:
            continue
        selected = (getattr(decision, "use_case_variants", None) or {}).get(uc)
        if selected in named:
            resp.extras["assumption"] = {
                "use_case": uc, "variant": selected,
                "reason": "workload_variant_explicitly_resolved",
                "note": f"Using the {selected.replace('_', ' ')} capability profile.",
            }
            return
        choices = [("base", R.resolve(vertical, uc, None) or {})]
        choices += [(v, R.resolve(vertical, uc, v) or {}) for v in named]
        lows = [c[1]["budget_band_hint"][0] for c in choices
                if isinstance(c[1].get("budget_band_hint"), (list, tuple)) and c[1]["budget_band_hint"]]
        if len(lows) < 2:
            continue
        gap = max(lows) - min(lows)
        if gap < _VARIANT_SPREAD_MIN_DOLLARS and gap / max(min(lows), 1) < _VARIANT_SPREAD_MIN:
            continue                              # variants don't move the floor enough to ask
        pinned = next((v for v in named if set(v.split("_")) & qtokens), None)
        if pinned:                                # the query already named a level → pin it silently
            resp.extras["assumption"] = {"use_case": uc, "variant": pinned,
                                         "note": f"Assuming {pinned.replace('_', ' ')} — say if not."}
            return
        opts = []
        for vid, r in choices:
            b = r.get("budget_band_hint")
            lbl = ("standard " + uc.replace("_", " ")) if vid == "base" else vid.replace("_", " ")
            if isinstance(b, (list, tuple)) and b:
                lbl += f" — from ~${int(b[0]):,}"
            opts.append({"id": vid, "label": lbl})
        resp.clarify.append({
            "id": f"variant_{uc}", "goal": "pick_use_case_variant",
            "reason": "missing_material_capability_slot",
            "missing_slots": ["use_case_variant"],
            "text": f"For {uc.replace('_', ' ')}, which level fits? It changes the pick and the price.",
            "options": opts})
        return


def _maybe_complement_offer(db, envelope: TurnEnvelope, decision: TurnDecision,
                            resp: CoreResponse) -> None:
    """Phase 1d.4 — the unstocked-complement trust play. A use-case can declare COMPLEMENTS
    (drawing → a graphics tablet for pen input). ONE declaration, two behaviours, picked by STOCK
    TRUTH (sells_within):
      • stocked   → bundle-upsell ('pair it with a …');
      • NOT stocked → a SOURCE-IT offer (supplier RFQ, human-approved) + a willing-to-wait CTA —
        turning a catalog gap into an honest alternative + a procurement trigger + a demand signal.
    Never blocks; NEVER auto-sends (the human-only-send invariant holds). No-op off the product
    lanes / on a degraded or off-catalog turn / when no complement is declared."""
    if decision.lane not in ("SEARCH", "FILTER") or resp.off_catalog or resp.degraded:
        return
    vertical = _vertical_name(decision.node_handle)
    if not vertical:
        return
    from src.app.services import use_case_registry as R
    from src.app.services.taxonomy_registry import get_node, sells_within
    offers: list = []
    seen: set = set()
    for uc in (decision.use_cases or ()):
        for comp in R.complements(vertical, uc):
            key, node = comp.get("key"), comp.get("node")
            if not key or key in seen or not node or get_node(node) is None:
                continue
            # SELF-COMPLEMENT suppression (review-10): don't offer 'pair with a graphics tablet'
            # when the shopper is ALREADY shopping the graphics-tablet node (or a descendant).
            if _is_descendant_or_self(decision.node_handle, node):
                continue
            seen.add(key)
            stocked = sells_within(db, node, tenant_id=envelope.tenant_id) is True
            offer = {"key": key, "label": comp.get("label") or key, "node": node,
                     "reason": comp.get("reason"), "tags": comp.get("tags") or [],
                     "stocked": stocked}
            if stocked:
                offer["mode"] = "bundle"
                # retrieve the complement's cheapest in-catalog price for a concrete framing +
                # the STANDALONE path ('already have a computer? just the tablet') — the
                # complement-as-primary inversion for a lower budget / existing device.
                import dataclasses
                from src.app.services.recommendation_core.evidence import gather_evidence
                free = dataclasses.replace(envelope, budget_min_cents=None, budget_max_cents=None)
                prices = [v.price_cents for v in gather_evidence(db, free, node_handle=node, limit=8).variants
                          if v.price_cents is not None]
                frm = f" (from ${min(prices) / 100:,.0f})" if prices else ""
                offer["from_cents"] = min(prices) if prices else None
                offer["prompt"] = (f"Pair your laptop with a {offer['label']}{frm} for pen input — "
                                   f"or, if you already have a computer, a {offer['label']} alone "
                                   f"does the job (no new laptop needed).")
                offer["options"] = [
                    {"id": "add_bundle", "label": f"Add a {offer['label']}{frm} to my laptop"},
                    {"id": "standalone", "label": f"Just the {offer['label']}{frm} — I have a computer"}]
            else:
                offer["mode"] = "source"
                offer["supplier_rfq_offer"] = True
                offer["prompt"] = (f"{offer['reason'] or offer['label'].capitalize()}. We don't "
                                   f"stock {offer['label']}s yet — I can raise a supplier request "
                                   f"(nothing is sent without human approval). Willing to wait?")
                offer["options"] = [
                    {"id": "source_it", "label": f"Yes — draft a supplier request for a {offer['label']}"},
                    {"id": "in_catalog", "label": "No — show me what does the job in stock"}]
            offers.append(offer)
    if offers:
        resp.extras["complement_offers"] = offers


def _bundle_floor(db, envelope: TurnEnvelope, decision: TurnDecision, vertical: Optional[str],
                  variants: list, reqs: Dict[str, Any]) -> Optional[int]:
    """The cheaper HYBRID per-unit floor: cheapest laptop meeting the requirements MINUS the
    on-device pen capability (touchscreen/form_factor) + the cheapest stocked complement (graphics
    tablet). What can make a bulk order fit when the touchscreen floor can't."""
    from src.app.services.recommendation_core.fit import build_cards
    non_device = {k: v for k, v in reqs.items() if k not in ("touchscreen", "form_factor")}
    _, s = build_cards(variants, non_device or None, limit=1)
    laptop = s.get("capability_floor_cents")
    if not laptop or not vertical:
        return None
    import dataclasses
    from src.app.services import use_case_registry as R
    from src.app.services.taxonomy_registry import sells_within
    free = dataclasses.replace(envelope, budget_min_cents=None, budget_max_cents=None)
    comp = None
    for uc in (decision.use_cases or ()):
        for c in R.complements(vertical, uc):
            node = c.get("node")
            if node and sells_within(db, node, tenant_id=envelope.tenant_id) is True:
                prices = [v.price_cents for v in gather_evidence(db, free, node_handle=node, limit=8).variants
                          if v.price_cents is not None]
                if prices:
                    comp = min(prices) if comp is None else min(comp, min(prices))
    return (laptop + comp) if comp else None


def _bulk_message(econ: Dict[str, Any], decision: TurnDecision) -> str:
    q, floor, total = econ["quantity"], econ["floor_cents"], econ.get("total_cents")
    uc = (list(getattr(decision, "use_cases", None) or ["your use case"]))[0].replace("_", " ")
    if econ["verdict"] == "unsized":
        return (f"For {q} units for {uc}, the per-unit floor is ${floor / 100:,.0f} — about "
                f"${econ['needed_cents'] / 100:,.0f} total. Tell me your budget and I'll size it.")
    if econ["verdict"] == "fits":
        return (f"Good news — {q} units for {uc} fit your ${total / 100:,.0f}: about "
                f"${econ['needed_cents'] / 100:,.0f} total at ${floor / 100:,.0f} each.")
    parts = [f"{q} units for {uc} need about ${econ['needed_cents'] / 100:,.0f} "
             f"(${floor / 100:,.0f} each), over your ${total / 100:,.0f}. Options:"]
    parts += ["• " + t["label"] for t in econ["tradeoffs"]]
    return " ".join(parts)


def _resolve_bulk_total(decision: TurnDecision, envelope: TurnEnvelope,
                        quantity: int) -> tuple:
    """The whole-order budget in CENTS, respecting budget_scope — returns (total, ambiguous).
    NEVER reinterprets a PER-UNIT budget as a total (review-10 P0 arithmetic-safety):
      • an explicit model total_budget wins;
      • a stated envelope budget tagged per_unit → × quantity; tagged total → as-is;
      • a stated-but-UNTAGGED budget → (None, True): ASK, don't guess the math."""
    if decision.total_budget_cents:
        return decision.total_budget_cents, False
    b = envelope.budget_max_cents
    if not b:
        return None, False
    scope = getattr(decision, "budget_scope", "unknown")
    if scope == "total":
        return b, False
    if scope == "per_unit":
        return b * quantity, False
    return None, True     # a budget was stated but scope is unknown → ambiguous, ask


def _maybe_bulk_economics(db, envelope: TurnEnvelope, decision: TurnDecision,
                          resp: CoreResponse) -> None:
    """Phase 1f — bulk-order economics: quantity (from the extracted `count`) + total budget → the
    ÷units viability + the tradeoff menu (increase budget / reduce units / bundle-fit / payment
    plan), reusing the capability floor and the complement bundle. Strips `count` from the fit
    requirements (a quantity signal, not a per-product predicate). Never blocks; degrades silently
    if it can't size. Fires whenever a quantity ≥ 2 is detected (bulk), any lane."""
    if resp.off_catalog or resp.degraded or not decision.node_handle:
        return
    quantity = resp.extras.get("requested_quantity")   # count stripped upstream (never in fit reqs)
    if not quantity or quantity < 2:
        return
    reqs = dict(decision.requirements or {})
    import dataclasses
    from src.app.services.recommendation_core.bulk import assess_bulk
    from src.app.services.recommendation_core.fit import build_cards
    free = dataclasses.replace(envelope, budget_min_cents=None, budget_max_cents=None)
    variants = _gather_scope_variants(db, free, decision, 10)   # device host FAMILY (Laptops + Gaming)
    if not variants:
        return
    floor = build_cards(variants, reqs or None, limit=1)[1].get("capability_floor_cents")
    if not floor:
        return
    # Buyer-facing order math must price something the buyer can actually select.  The
    # capability floor may come from an unshown product outside a stated lower budget bound
    # (for example $629 while the visible slate starts at $1,599), which made the total both
    # arithmetically correct and commercially false.  Use the cheapest non-failing shown card
    # as the actionable floor; retain the capability floor only when no eligible card is shown.
    shown_prices = [
        int(card.price_cents)
        for card in resp.products
        if card.price_cents is not None
        # Unknown means the catalog lacks enough evidence to authorize this workload. It may
        # appear in a clearly labeled nearest-fit tier, but must never become the financial
        # capability floor or turn an unsuitable bulk order into a false "fits" verdict.
        and str((card.fit or {}).get("overall") or "unknown") == "meets"
    ]
    if shown_prices:
        floor = min(shown_prices)
    vertical = _vertical_name(decision.node_handle)
    total, scope_ambiguous = _resolve_bulk_total(decision, envelope, quantity)   # P0: scope-safe
    # Bundle discovery is an optional upsell leg.  Missing companion/supplier tables must not
    # suppress the primary quantity x price arithmetic for the order itself.
    try:
        bundle_floor = _bundle_floor(db, envelope, decision, vertical, variants, reqs)
    except Exception as exc:
        logger.info("bulk bundle floor unavailable; base order sizing retained: %s", repr(exc)[:120])
        bundle_floor = None
    econ = assess_bulk(quantity, total, floor, bundle_floor_cents=bundle_floor)
    if not econ:
        return
    resp.extras["bulk"] = econ
    if scope_ambiguous:
        # a budget was stated but we can't tell per-unit vs total — ASK, never guess the arithmetic
        per = f"${(envelope.budget_max_cents or 0) / 100:,.0f}"
        econ["scope_ambiguous"] = True
        resp.set_message((f"For {quantity} units — is {per} your budget PER LAPTOP, or the TOTAL for "
                          f"all {quantity}? That changes the math."), MsgPriority.BULK_SCOPE_CLARIFY)
        if not resp.clarify:
            resp.clarify.append({"id": "budget_scope", "goal": "resolve_budget_scope",
                                 "text": f"Is {per} per laptop, or the total for all {quantity}?",
                                 "options": [{"id": "per_unit", "label": f"{per} per laptop"},
                                             {"id": "total", "label": f"{per} total for all {quantity}"}]})
    else:
        resp.set_message(_bulk_message(econ, decision), MsgPriority.BULK_VERDICT)


def _maybe_fulfillment_preview(envelope: TurnEnvelope, decision: TurnDecision,
                               resp: CoreResponse) -> None:
    """Project bulk availability through the mature, read-only fulfillment stage.

    V2 owns recommendation advice, not procurement execution. Forcing deferred mode here
    preserves that boundary: the stage may expose stock, transfer, shortfall and a sourcing
    intent, but a durable case is still created only when the buyer confirms the cart.
    """
    quantity = resp.extras.get("requested_quantity")
    if not quantity or int(quantity) < 2 or not resp.products:
        return

    from src.app.config import get_settings, load_feature_flags
    from src.app.services.recommend_fulfillment_stage import run_fulfillment_stage

    flags = load_feature_flags(get_settings().feature_flags_path)
    flags["FULFILLMENT_DEFER_TO_CART"] = True
    constraints: Dict[str, Any] = {
        "order_quantity": int(quantity),
        "budget_min": (envelope.budget_min_cents / 100
                       if envelope.budget_min_cents is not None else None),
        "budget_max": (envelope.budget_max_cents / 100
                       if envelope.budget_max_cents is not None else None),
        "use_case": decision.use_cases[0] if decision.use_cases else None,
    }
    # Delivery language is a typed procurement constraint, not narration.
    # Preserve the decomposer's bounded day count when projecting the V2 slate
    # into the read-only fulfillment stage.
    from src.app.services.query_decomposer import decompose

    horizon_days = decision.operational_constraints.get("delivery_window_days")
    if horizon_days is None:
        horizon_days = decompose(envelope.query).availability_horizon_days
    if horizon_days is not None:
        constraints["availability_horizon_days"] = int(horizon_days)
    payment_plan = decision.operational_constraints.get("payment_plan")
    if payment_plan:
        constraints["payment_plan"] = str(payment_plan)
    projection: Dict[str, Any] = {}
    availability_line = run_fulfillment_stage(
        results=[product.as_dict() for product in resp.products],
        constraints=constraints,
        payload=projection,
        uid=envelope.uid,
        trace_id=envelope.trace_id,
        flags=flags,
        query=envelope.query,
        tenant_id=envelope.tenant_id,
        # The shared core has already authorized one canonical slate. Re-parsing the raw
        # sentence as a cart manifest can turn audience phrases such as "20 students"
        # into phantom line items and replace the selected SKU with a legacy alias.
        allow_query_order_split=False,
    )
    if availability_line and availability_line.lower() not in resp.message.lower():
        resp.message = " ".join(
            part for part in (resp.message.strip(), availability_line.strip()) if part
        )
    for key in ("availability", "fulfillment_options", "sourcing_intent"):
        if projection.get(key) is not None:
            resp.extras[key] = projection[key]


def _bind_compare_targets(variants, targets) -> Optional[list]:
    """R9.3 — bind each model-NAMED compare target ('dell g16') to a retrieved variant by
    distinctive-token overlap (the cart-resolver DF discipline: a token unique across the
    slate identifies; a tie never binds). Returns the bound variants in TARGET order only when
    ≥2 DISTINCT units bound — anything less keeps the whole slate (a comparison narrowed to
    the wrong or a single unit is worse than showing the category)."""
    import re
    def tok(value):
        return set(re.findall(r"[a-z0-9]+", (value or "").lower()))
    title_toks = {v.sku: tok(v.title) for v in variants}
    df: Dict[str, int] = {}
    for toks in title_toks.values():
        for t in toks:
            df[t] = df.get(t, 0) + 1
    bound, seen = [], set()
    for target in targets:
        t_toks = tok(target)
        scored = []
        for v in variants:
            overlap = t_toks & title_toks[v.sku]
            unique_hits = sum(1 for x in overlap if df.get(x) == 1)   # df==1 identifies
            if unique_hits:
                scored.append((unique_hits, len(overlap), v))
        if not scored:
            continue
        scored.sort(key=lambda s: (-s[0], -s[1]))
        if len(scored) > 1 and scored[0][:2] == scored[1][:2]:
            continue                                # tie = ambiguous → this target stays unbound
        v = scored[0][2]
        if v.sku not in seen:
            seen.add(v.sku)
            bound.append(v)
    return bound if len(bound) >= 2 else None


def _compare_currency_conflict(all_variants, eligible_variants, targets,
                               settlement_currency: str) -> Optional[Dict[str, Any]]:
    """Return an explicit conflict when a fully bound named comparison loses a target
    at the currency gate. A one-card response is not a valid two-product comparison."""
    bound = _bind_compare_targets(all_variants, targets)
    if not bound:
        return None
    eligible_skus = {variant.sku for variant in eligible_variants}
    excluded = [variant for variant in bound if variant.sku not in eligible_skus]
    if not excluded:
        return None
    return {
        "settlement_currency": str(settlement_currency or "").upper(),
        "excluded": [{"sku": variant.sku, "title": variant.title,
                      "currency": str(variant.currency or "").upper()}
                     for variant in excluded],
        "fx_applied": False,
    }


def _disambiguate_compare_legs(db, envelope: TurnEnvelope, legs: list) -> list:
    """Narrow a mixed-product comparison leg using approved taxonomy truth.

    One unambiguous leg may identify the shared product type. Conflicting unambiguous legs are
    left untouched so legitimate cross-category comparisons remain possible.
    """
    all_variants = [variant for leg in legs for variant in getattr(leg, "variants", [])]
    nodes = classification_nodes_for_skus(
        db, [variant.sku for variant in all_variants], tenant_id=envelope.tenant_id,
    )
    leg_nodes = [
        {nodes[variant.sku] for variant in getattr(leg, "variants", []) if variant.sku in nodes}
        for leg in legs
    ]
    anchors = {next(iter(values)) for values in leg_nodes if len(values) == 1}
    if len(anchors) != 1:
        return legs
    anchor = next(iter(anchors))
    for leg, values in zip(legs, leg_nodes):
        if len(values) <= 1 or anchor not in values:
            continue
        narrowed = [variant for variant in leg.variants if nodes.get(variant.sku) == anchor]
        if narrowed:
            leg.variants = narrowed
    return legs


def _currency_eligible_variants(variants: list, envelope: TurnEnvelope,
                                resp: CoreResponse) -> list:
    """Apply the tenant/store settlement currency as a hard eligibility boundary.

    Cross-currency ranking is only valid with a bounded FX quote. The envelope currently carries
    no such quote, so mismatched and missing currency rows are excluded instead of compared by
    their raw numeric price.
    """
    requested = envelope.currency.strip().upper()
    eligible = [v for v in variants if str(v.currency or "").strip().upper() == requested]
    excluded = len(variants) - len(eligible)
    resp.extras["currency_policy"] = {
        "currency": requested,
        "excluded_mismatched": excluded,
        "fx_applied": False,
    }
    if excluded and not eligible:
        resp.set_message(
            f"The available matches are not priced in {requested}. I won't compare "
            "unconverted amounts; provide an approved FX quote or choose the store currency.",
            MsgPriority.LANE_BASE,
        )
    return eligible


def _retrieve_prior_shortlist(db, envelope: TurnEnvelope, decision: TurnDecision,
                              resp: CoreResponse, limit: int) -> bool:
    """R9.4: retrieve the prior turn's SHOWN SKUs (subject continuity) and, for EXPLAIN,
    compose a deterministic explanation of the top pick from its fit verdicts — no prose
    invention, only what the cards already carry. Returns False (fall back to node retrieval)
    when the shortlist can't be loaded — degrading to category is better than empty."""
    try:
        from src.app.services.catalog_read_model import get_variants
        variants = [v for v in get_variants(db, list(decision.prior_shortlist),
                                            tenant_id=envelope.tenant_id) if v.active]
    except Exception as exc:
        logger.warning("prior-shortlist retrieval failed: %s", repr(exc)[:120])
        return False
    if not variants:
        return False
    variants = _currency_eligible_variants(variants, envelope, resp)
    # Subject continuity does not override the current accepted constraints.
    # Replaying an earlier shortlist after a buyer changed their price range or
    # brand boundary otherwise makes the trace and visible cards disagree.
    lo, hi = envelope.budget_min_cents, envelope.budget_max_cents
    if lo is not None or hi is not None:
        variants = [
            variant for variant in variants
            if variant.price_cents is not None
            and (lo is None or variant.price_cents >= lo)
            and (hi is None or variant.price_cents <= hi)
        ]
    if decision.brand_filter:
        brand = decision.brand_filter.strip().lower()
        variants = [
            variant for variant in variants
            if (variant.brand or "").strip().lower() == brand
        ]
    if decision.exclude_brand:
        excluded = decision.exclude_brand.strip().lower()
        variants = [
            variant for variant in variants
            if (variant.brand or "").strip().lower() != excluded
        ]
    if not variants:
        return False
    resp.extras["evidence"] = {"retrieval_mode": "prior_shortlist", "count": len(variants),
                               "skus": [v.sku for v in variants]}
    # a NAMED compare over the shortlist ('the ROG vs the Katana') narrows the same way (R9.3)
    if decision.lane == "COMPARE" and decision.compare_targets:
        pair = _bind_compare_targets(variants, decision.compare_targets)
        if pair:
            variants = pair
            resp.extras["compare_bound"] = [v.sku for v in pair]
    cards, summary = build_cards(variants, decision.requirements or None, limit=limit,
                                 sort=decision.sort, preferred=_preferred_values(resp))
    resp.products = cards
    if decision.requirements:
        resp.fit_summary = summary
    if cards:
        # deterministic explanation for BOTH consuming lanes ('why is the first one better?'
        # routes as EXPLAIN or COMPARE run-to-run) — only what the cards already carry.
        top = cards[0]
        why = "; ".join(top.why) if top.why else "it leads the shortlist on price and availability"
        price = (f" at {top.currency} {top.price_cents / 100:,.0f}"
                 if top.price_cents is not None else "")
        resp.set_message(f"{top.title}{price} leads this shortlist: {why}.", MsgPriority.LANE_BASE)
    return True

def _exec_retrieve(db, envelope: TurnEnvelope, decision: TurnDecision,
                   resp: CoreResponse, limit: int) -> None:
    # R9.4 — SHORTLIST CONSUMPTION (review-6 #17 closed): an EXPLAIN/COMPARE turn whose subject
    # came from the SESSION ('why is the first one better for me?') is about the items ACTUALLY
    # SHOWN last turn — retrieve exactly those SKUs in their shown order, never a fresh category
    # sweep that may not even contain 'the first one'. A turn that named its own node (a fresh
    # 'compare X vs Y') keeps the normal node retrieval.
    if (decision.lane in ("EXPLAIN", "COMPARE") and decision.subject_from_session
            and decision.prior_shortlist):
        if _retrieve_prior_shortlist(db, envelope, decision, resp, limit):
            return
    bundle = None
    if decision.lane == "COMPARE" and len(decision.compare_targets) >= 2:
        # A fresh named comparison often has no single taxonomy node: the model correctly
        # identifies the two product names, while searching the joined "X versus Y" phrase
        # matches neither. Retrieve each bounded target independently, then let the existing
        # deterministic binder authorize the exact catalog variants. At most four targets are
        # admitted by the router clamp, so this cannot become an unbounded retrieval fan-out.
        legs = []
        merged, seen = [], set()
        for target in decision.compare_targets:
            target_env = dataclasses.replace(envelope, query=str(target))
            leg = gather_evidence(
                db, target_env, node_handle=None, text_query=str(target),
                limit=max(limit * 2, 20),
            )
            legs.append(leg)
        legs = _disambiguate_compare_legs(db, envelope, legs)
        for leg in legs:
            if leg.status == "ok":
                for variant in leg.variants:
                    if variant.sku not in seen:
                        seen.add(variant.sku)
                        merged.append(variant)
        if merged and _bind_compare_targets(merged, decision.compare_targets):
            bundle = legs[0]
            bundle.variants = merged
            bundle.status = "ok"
            bundle.grounding = "grounded"
            bundle.retrieval_mode = "named_compare_union"
            bundle.queries = sum(leg.queries for leg in legs)
            bundle.latency_ms = sum(leg.latency_ms for leg in legs)
            bundle.total_before_budget = sum(leg.total_before_budget for leg in legs)
            bundle.budget_filtered = sum(leg.budget_filtered for leg in legs)
            bundle.errors = [err for leg in legs for err in leg.errors]
    if bundle is None:
        qualified_candidate_skus = [
            str(value) for value in (resp.extras.get("catalog_qualification_candidates") or [])
            if value
        ][:100]
        bundle = gather_evidence(db, envelope, node_handle=decision.node_handle,
                                 limit=max(limit * 3, 30),
                                 exact_skus=([decision.exact_product_sku]
                                             if decision.exact_product_sku
                                             else (qualified_candidate_skus or None)))
    # RETRIEVAL SCOPE UNION (Phase 1.5 fix): when the routed node is a workload-HOST device with
    # capability requirements, augment the candidate set with the store's device host UNION
    # (Laptops + Gaming Laptops) — mirroring the capability FLOOR, which already spans the union via
    # _capability_scope_nodes. Retrieval was LEAF-ONLY, so a qualifying high-VRAM Gaming Laptop
    # classified under a sibling node was never even a candidate and closest-match faithfully showed
    # FAILING laptops (the source of the gpu_vram_gb/ram_gb replay 'failures' — a retrieval gap, not
    # a ranking bug). Budget stays applied (real envelope, not the free floor env).
    if (decision.requirements and not decision.exact_product_sku
            and _is_workload_host_product(decision.node_handle)):
        _siblings = [n for n in _capability_scope_nodes(decision)
                     if n and n != decision.node_handle]
        if _siblings:
            _merged = list(bundle.variants)
            _seen = {v.sku for v in _merged}
            for _node in _siblings:
                _b = gather_evidence(db, envelope, node_handle=_node, limit=max(limit * 3, 30))
                if _b.status == "ok":
                    for _v in _b.variants:
                        if _v.sku not in _seen:
                            _seen.add(_v.sku)
                            _merged.append(_v)
            if len(_merged) != len(bundle.variants):
                bundle.variants = _merged
                bundle.retrieval_mode = "taxonomy_union:" + "+".join([decision.node_handle] + _siblings)
            if _merged and bundle.status != "ok":
                bundle.status = "ok"   # a sibling host node supplied candidates the leaf lacked
    # broad-retry ONLY on a valid empty (never on error — that would mask a failure): no node
    # matched and the phrase LIKE-matches nothing ('play valorant at 144fps') but we HAVE
    # clamped requirements = retrieval intent enough; rank the catalog by fit (closest-match
    # honesty beats an empty grid).
    if bundle.status == "empty" and decision.requirements:
        # SCOPE the broad retry to the requested product's VERTICAL (review-8, pharmacy-bleed): the
        # old broad=True path text-searched the whole catalog ordered by price ASC, so cheap
        # pharmacy floated into an empty electronics-accessory node ('a mouse for gaming' → Hand
        # Sanitiser). Retrieve the vertical-root subtree instead — electronics stays electronics;
        # hb-* (pharmacy) can never appear. Only when no node routed do we fall to the old text leg.
        # scope to the routed node's vertical; if no node routed (ungrounded workload the reroute
        # couldn't ground either), fall to the store's workload-host root — NEVER the whole catalog.
        vroot = _vertical_root(decision.node_handle) or _first_workload_host_root()
        if vroot:
            bundle = gather_evidence(db, envelope, node_handle=vroot, limit=max(limit * 5, 60))
            bundle.retrieval_mode = f"vertical_broad:{vroot}"
        else:
            bundle = gather_evidence(db, envelope, broad=True, limit=max(limit * 5, 60))
            bundle.retrieval_mode = "requirements_broad"
    resp.extras["evidence"] = bundle.as_trace()
    if bundle.status == "error":
        resp.degraded = True         # a retrieval FAILURE degrades — never present as 'no match'
        return
    variants = _currency_eligible_variants(bundle.variants, envelope, resp)
    if decision.lane == "COMPARE" and len(decision.compare_targets) >= 2:
        conflict = _compare_currency_conflict(
            bundle.variants, variants, decision.compare_targets, envelope.currency)
        if conflict:
            resp.extras["compare_currency_conflict"] = conflict
            mismatched = ", ".join(
                f"{item['title']} ({item['currency'] or 'currency unknown'})"
                for item in conflict["excluded"])
            resp.set_message(
                f"I can't compare both requested products against a {envelope.currency} budget: "
                f"{mismatched} is outside the store currency. Provide an approved FX quote or "
                "choose products in one currency.",
                MsgPriority.LANE_BASE,
            )
            variants = []
    # BRAND FILTER (R9.2 — 'only Asus'): clamped upstream to a REAL catalog brand, applied
    # HONESTLY — zero matches shows an honest empty message, never the unfiltered slate (a
    # grid that silently ignored the shopper's filter is the answer-shape lie).
    if decision.brand_filter:
        bl = decision.brand_filter.lower()
        variants = [v for v in variants if (v.brand or "").strip().lower() == bl]
        if not variants:
            resp.set_message((f"None of the current options are from {decision.brand_filter} — "
                              f"tell me if another brand works, or widen the search."),
                             MsgPriority.LANE_BASE)
    # brand EXCLUSION ('but not Apple') — subtract the excluded brand from the shown slate
    if decision.exclude_brand:
        xb = decision.exclude_brand.strip().lower()
        variants = [v for v in variants if (v.brand or "").strip().lower() != xb]
    if decision.node_handle is None:
        inferred_subject = _inferred_subject_from_variants(variants)
        if inferred_subject:
            resp.extras["constraints_used"]["node_handle"] = inferred_subject
            resp.extras["subject_inferred_from_slate"] = inferred_subject
    # COMPARE of NAMED units (R9.3): narrow to the products the shopper actually named — the
    # compare_two_models case returned the whole category instead of the Dell G16 vs the Lenovo.
    if decision.lane == "COMPARE" and decision.compare_targets:
        pair = _bind_compare_targets(variants, decision.compare_targets)
        if pair:
            variants = pair
            names = " vs ".join((v.title or v.sku)[:48] for v in pair)
            resp.set_message(f"Comparing {names}.", MsgPriority.LANE_BASE)
            resp.extras["compare_bound"] = [v.sku for v in pair]
    cards, summary = build_cards(variants, decision.requirements or None, limit=limit,
                                 sort=decision.sort, preferred=_preferred_values(resp))
    # A wider top-5/top-10 view is still the primary eligible slate, not an
    # unlabeled mixture of valid products and known capability failures. Keep
    # closest alternatives only when the catalog has no meeting product at all.
    if decision.requirements and decision.lane in ("SEARCH", "FILTER", "PROCUREMENT"):
        meeting = [c for c in cards if (c.fit or {}).get("overall") == "meets"]
        if meeting:
            cards = meeting
    resp.products = cards
    if decision.requirements:
        resp.fit_summary = summary
        if summary.get("closest_match_mode"):
            # reuse build_cards' SAFE requirement descriptions — an enum predicate has a LIST
            # threshold that a numeric formatter (float(t)) crashes on (live-caught).
            reqs = ", ".join(f"{k} {d}" for k, d in (summary.get("requirements") or {}).items())
            # CAPABILITY-CONFLICT narration (1f): discover from the CATALOG which requirement, if
            # relaxed, would match — the intelligent 'why' + tradeoff (no touchscreen 2-in-1 has a
            # 12GB discrete GPU). Data-derived, not a hardcoded 'X conflicts with Y' rule.
            from src.app.services.recommendation_core.fit import relaxation_options
            opts = relaxation_options(variants, decision.requirements)
            if opts:
                _lbl = {"touchscreen": "the touchscreen", "gpu_vram_gb": "the discrete GPU",
                        "form_factor": "the 2-in-1/tablet form", "ram_gb": "the RAM",
                        "storage_gb": "the storage", "refresh_hz": "the high refresh rate"}

                def _lab(o):
                    return _lbl.get(o["key"], o["key"].replace("_", " "))
                tail = (f", or {opts[1]['count']} if you relax {_lab(opts[1])}"
                        if len(opts) >= 2 else "")
                resp.set_message((f"No single product has all of {reqs} together — {opts[0]['count']} "
                                  f"match if you relax {_lab(opts[0])}{tail}. Which matters more?"),
                                 MsgPriority.LANE_BASE)
                resp.extras["capability_conflict"] = {"requirements": reqs, "relax_options": opts}
            else:
                resp.set_message((f"No product in our catalog meets {reqs} — showing the closest "
                                  f"options, ranked by how near they come."), MsgPriority.LANE_BASE)


def _apply_secondary_explanation(decision: TurnDecision, resp: CoreResponse) -> None:
    """Answer a compound EXPLAIN obligation from the authorized product verdict."""
    if "EXPLAIN" not in decision.secondary_lanes or not resp.products:
        return
    top = resp.products[0]
    verdict = str((top.fit or {}).get("overall") or "")
    reasons = "; ".join(top.why[:3]) if top.why else "it ranks highest on the authorized slate"
    if verdict == "meets":
        explanation = f"Why {top.title} leads: {reasons}."
    elif verdict:
        explanation = (
            f"Why {top.title} is shown: {reasons}. It is an alternative, not a full match."
        )
    else:
        explanation = f"Why {top.title} leads: {reasons}."
    resp.extras["explanation"] = {
        "sku": top.sku,
        "verdict": verdict or None,
        "basis": list(top.why[:3]),
    }
    current = str(resp.message or "").strip()
    if explanation not in current:
        resp.message = f"{current} {explanation}".strip()


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
    node_label = decision.requested_category_label or decision.node_path or "that category"
    resp.off_catalog = {"class": decision.node_handle, "label": node_label,
                        "supplier_rfq_offer": True}


def _exec_clarify(db, envelope: TurnEnvelope, decision: TurnDecision,
                  resp: CoreResponse, limit: int) -> None:
    resp.clarify.append({"question": "Could you tell me a bit more about what you need "
                                     "(budget, brand, or intended use)?",
                         "reason": "low_routing_confidence"})


def _exec_policy_answer(db, envelope: TurnEnvelope, decision: TurnDecision,
                        resp: CoreResponse, limit: int) -> None:
    from src.app.services.policy_answer_service import policy_answer

    answer = policy_answer(envelope.query, tenant_id=envelope.tenant_id)
    resp.extras["policy_topic"] = answer["topic"]
    resp.extras["policy_source"] = answer["source"]
    resp.extras["policy_answered"] = answer["answered"]
    resp.extras["action_executed"] = answer["action_executed"]
    resp.set_message(answer["message"], MsgPriority.LANE_BASE)


def _exec_handoff_support(db, envelope: TurnEnvelope, decision: TurnDecision,
                          resp: CoreResponse, limit: int) -> None:
    from src.app.services.support_handoff_advice import prepare_support_handoff

    advice = prepare_support_handoff(envelope.query, tenant_id=envelope.tenant_id)
    resp.extras.update({key: value for key, value in advice.items() if key != "message"})
    resp.set_message(advice["message"], MsgPriority.LANE_BASE)


def _exec_handoff_procurement(db, envelope: TurnEnvelope, decision: TurnDecision,
                              resp: CoreResponse, limit: int) -> None:
    if decision.case_operation in ("status", "summary", "amendment"):
        session = envelope.session or {}
        accepted = session.get("accepted_constraints") if isinstance(
            session.get("accepted_constraints"), dict
        ) else {}
        sku = decision.exact_product_sku
        quantity = decision.quantity
        case_id = (session.get("fulfillment_case_id") or session.get("procurement_case_id")
                   or session.get("sourcing_request_id"))
        anchor = " · ".join(
            value for value in (
                sku,
                f"{quantity} units" if quantity else None,
                f"case {case_id}" if case_id else None,
            ) if value
        )
        message = (
            "I kept the selected product and cart unchanged and recorded the "
            "delivery/payment requirements for the next confirmation check"
            if decision.case_operation == "amendment"
            else "Your procurement case is still active"
        )
        if anchor:
            message += f" for {anchor}"
        if decision.case_operation == "amendment":
            message += ". No new product search or commercial execution was started."
        else:
            message += ". I kept the existing product and case context; no new search or commercial action was started."
        resp.extras.update({
            "case_operation": decision.case_operation,
            "preserve_current_view": True,
            "state_changed": False,
            "case_anchor": {
                "sku": sku,
                "quantity": quantity,
                "case_id": case_id,
                "destination_token": accepted.get("destination_token"),
                "deadline": accepted.get("deadline"),
            },
        })
        resp.set_message(message, MsgPriority.LANE_BASE)
        return
    from .procurement import build_procurement_advice
    advice = build_procurement_advice(envelope)
    resp.extras.update({key: value for key, value in advice.items() if key != "message"})
    resp.set_message(advice["message"], MsgPriority.LANE_BASE)


def _exec_inventory_summary(db, envelope: TurnEnvelope, decision: TurnDecision,
                            resp: CoreResponse, limit: int) -> None:
    from src.app.services.inventory_read_advice import inventory_summary

    advice = inventory_summary(resp.products, tenant_id=envelope.tenant_id)
    resp.extras["inventory_source"] = advice["source"]
    resp.extras["inventory_answered"] = advice["answered"]
    resp.extras["action_executed"] = advice["action_executed"]
    resp.set_message(advice["message"], MsgPriority.LANE_BASE)


_EXECUTORS: Dict[str, Any] = {
    "retrieve": _exec_retrieve,
    "fit_check": _exec_fit_check,
    "off_catalog_honesty": _exec_off_catalog,
    "clarify": _exec_clarify,
    "policy_answer": _exec_policy_answer,
    "handoff_support": _exec_handoff_support,
    "handoff_procurement": _exec_handoff_procurement,
    "inventory_summary": _exec_inventory_summary,
}
