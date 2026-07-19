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
import time
from typing import Any, Callable, Dict, Optional

from src.app.services.recommendation_core.envelope import CoreResponse, MsgPriority, TurnEnvelope
from src.app.services.recommendation_core.evidence import (
    degraded_response,
    gather_evidence,
)
from src.app.services.recommendation_core.fit import build_cards
from src.app.services.recommendation_core.plan import Plan, derive_plan
from src.app.services.recommendation_core.turn_router import TurnDecision, route_turn
from src.app.services.taxonomy_registry import ancestors, get_node, grounding_status

logger = logging.getLogger("shopsquire.recommendation_core.core")

LLMFn = Callable[[str, float], str]


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
    # time the whole DECIDE phase (the ~7s router model call + KB intent resolution + reroute +
    # continuation inheritance) — this is the turn's dominant latency, so the canary can attribute
    # the p50 to the model call vs the deterministic stages (P1 instrumentation).
    _t_route = time.perf_counter()
    decision = route_turn(db, envelope, llm_fn=llm_fn)
    # The HTTP contract may not pre-parse a textual budget.  The model maps its value and
    # scope; deterministic arithmetic turns that bounded proposal into the per-unit ceiling
    # used by evidence retrieval.  A total budget for N units is never treated as per-unit.
    if (envelope.budget_min_cents is None and envelope.budget_max_cents is None
            and decision.total_budget_cents is not None):
        per_unit_cap = None
        if decision.budget_scope == "per_unit":
            per_unit_cap = decision.total_budget_cents
        elif decision.budget_scope == "total":
            per_unit_cap = decision.total_budget_cents // max(1, decision.quantity or 1)
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
                            vertical=_vertical_name(decision.node_handle))
    resolved_reqs = intent["requirements"]
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
            logger.info("ungrounded-workload reroute → host %s (reqs=%s)", host,
                        sorted(decision.requirements))
    # R9.1 CONTINUATION INHERITANCE (screenshot 30 — the budget-loss bug): a refinement turn
    # ('show me cheaper ones') restates neither the budget nor the specs, so they vanished and
    # the follow-up re-anchored to the whole catalog. On a CONTINUATION lane only (the same
    # lanes whose nodeless turns inherit prior_node — M3-C2), adopt the session's accepted
    # constraints ADOPT-IF-ABSENT: a budget/requirement the shopper states THIS turn always
    # wins; a fresh SEARCH never inherits (context-rot guard, ledger §8). Runs BEFORE
    # derive_plan so fit_check comes back for inherited requirements.
    budget_inherited = requirements_inherited = False
    if (decision.lane in ("FILTER", "COMPARE", "EXPLAIN")
            and decision.subject_action != "switch"):
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
        # BULK continuation: inherit quantity + total budget when THIS turn didn't state them
        # ('how many can I get?' keeps the prior 6 units + $19k); a stated value this turn wins.
        if decision.quantity is None and acc.get("quantity"):
            decision = dataclasses.replace(decision, quantity=int(acc["quantity"]))
        if decision.total_budget_cents is None and acc.get("total_budget_cents"):
            decision = dataclasses.replace(decision, total_budget_cents=int(acc["total_budget_cents"]))
        # BRAND continuation (review-10 P0.6): inherit brand constraints when THIS turn didn't set
        # one ('show me cheaper ones' keeps the prior 'only Asus' / 'not Apple'); stated wins.
        if decision.brand_filter is None and acc.get("brand_filter"):
            decision = dataclasses.replace(decision, brand_filter=str(acc["brand_filter"]))
        if decision.exclude_brand is None and acc.get("exclude_brand"):
            decision = dataclasses.replace(decision, exclude_brand=str(acc["exclude_brand"]))
        if decision.preferred_brand is None and acc.get("preferred_brand"):
            decision = dataclasses.replace(decision, preferred_brand=str(acc["preferred_brand"]))

    # quantity is MODEL-JUDGED now (decision.quantity, clamped in the router) — no count-in-fit hack;
    # the router also excludes `count` from requirements, so nothing pollutes fit/closest-match.
    requested_quantity = decision.quantity

    plan = derive_plan(decision)   # model plan refinement arrives with the plan-proposal leg

    resp = CoreResponse(envelope=envelope, lane=decision.lane, grounding=grounding)
    resp.record_stage("route+intent", status="ok",
                      latency_ms=(time.perf_counter() - _t_route) * 1000.0,
                      won_message=False, source=decision.source)
    resp.extras["decision"] = decision.as_dict()
    if requested_quantity is not None:
        resp.extras["requested_quantity"] = requested_quantity
    resp.extras["plan"] = plan.as_dict()
    # the resolver's reasoning, surfaced for the 'Why Recommended' decision-trace tab
    resp.extras["intent"] = {"use_cases": intent["use_cases"],
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
        "use_cases": intent["use_cases"],
        "brands": [decision.brand_filter] if decision.brand_filter else [],
        "brand_excludes": [decision.exclude_brand] if decision.exclude_brand else [],
        "preferred_brands": [decision.preferred_brand] if decision.preferred_brand else [],
        "budget_cap_mode": decision.budget_cap_mode,
        # provenance (R9.1): the trace must say when this turn's constraints came from the
        # SESSION, not the message — and postflight persists what was USED, so a budget-less
        # follow-up refreshes the remembered budget instead of wiping it.
        "budget_inherited": budget_inherited,
        "requirements_inherited": requirements_inherited,
    }

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
    if decision.lane not in ("SEARCH", "FILTER"):
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
    if decision.lane not in ("SEARCH", "FILTER"):
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
        bands.append(_band("best_fit", "Best fit for you", "intent+budget", band1))

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
        if envelope.budget_max_cents is not None or envelope.budget_min_cents is not None:
            resp.extras["assumption"] = {           # the budget picks the tier — state, don't ask
                "use_case": uc, "variant": None,
                "note": f"Your budget picks the {uc.replace('_', ' ')} level — tell me if you meant "
                        f"a different one."}
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
    vertical = _vertical_name(decision.node_handle)
    total, scope_ambiguous = _resolve_bulk_total(decision, envelope, quantity)   # P0: scope-safe
    econ = assess_bulk(quantity, total, floor,
                       bundle_floor_cents=_bundle_floor(db, envelope, decision, vertical, variants, reqs))
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


def _bind_compare_targets(variants, targets) -> Optional[list]:
    """R9.3 — bind each model-NAMED compare target ('dell g16') to a retrieved variant by
    distinctive-token overlap (the cart-resolver DF discipline: a token unique across the
    slate identifies; a tie never binds). Returns the bound variants in TARGET order only when
    ≥2 DISTINCT units bound — anything less keeps the whole slate (a comparison narrowed to
    the wrong or a single unit is worse than showing the category)."""
    import re
    tok = lambda s: set(re.findall(r"[a-z0-9]+", (s or "").lower()))
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
        price = f" at ${top.price_cents / 100:,.0f}" if top.price_cents is not None else ""
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
    bundle = gather_evidence(db, envelope, node_handle=decision.node_handle,
                             limit=max(limit * 3, 30))
    # RETRIEVAL SCOPE UNION (Phase 1.5 fix): when the routed node is a workload-HOST device with
    # capability requirements, augment the candidate set with the store's device host UNION
    # (Laptops + Gaming Laptops) — mirroring the capability FLOOR, which already spans the union via
    # _capability_scope_nodes. Retrieval was LEAF-ONLY, so a qualifying high-VRAM Gaming Laptop
    # classified under a sibling node was never even a candidate and closest-match faithfully showed
    # FAILING laptops (the source of the gpu_vram_gb/ram_gb replay 'failures' — a retrieval gap, not
    # a ranking bug). Budget stays applied (real envelope, not the free floor env).
    if decision.requirements and _is_workload_host_product(decision.node_handle):
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
    variants = bundle.variants
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
    resp.set_message(("Good question — our policy details are being routed to the right lane; "
                      "here's what I can confirm from the store profile."), MsgPriority.LANE_BASE)


def _exec_handoff_support(db, envelope: TurnEnvelope, decision: TurnDecision,
                          resp: CoreResponse, limit: int) -> None:
    resp.extras["needs_human_review"] = True
    # review-10: 'received' + 'I've logged this' FALSELY implies a persisted claim — nothing is
    # filed here yet. Be honest until an idempotent handoff returns a real claim ID + audit event.
    resp.extras["claim_status"] = "pending_handoff"
    resp.set_message(("I'll pass this to a human to review — nothing is filed automatically yet. "
                      "You'll be contacted with next steps."), MsgPriority.LANE_BASE)


def _exec_handoff_procurement(db, envelope: TurnEnvelope, decision: TurnDecision,
                              resp: CoreResponse, limit: int) -> None:
    from .procurement import build_procurement_advice
    advice = build_procurement_advice(envelope)
    resp.extras.update({key: value for key, value in advice.items() if key != "message"})
    resp.set_message(advice["message"], MsgPriority.LANE_BASE)


_EXECUTORS: Dict[str, Any] = {
    "retrieve": _exec_retrieve,
    "fit_check": _exec_fit_check,
    "off_catalog_honesty": _exec_off_catalog,
    "clarify": _exec_clarify,
    "policy_answer": _exec_policy_answer,
    "handoff_support": _exec_handoff_support,
    "handoff_procurement": _exec_handoff_procurement,
}
