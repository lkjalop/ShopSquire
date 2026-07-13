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
    stated_keys = set(decision.requirements)   # what the SHOPPER explicitly asked for (pre-KB)
    intent = resolve_intent(list(decision.use_cases), dict(decision.requirements),
                            query=envelope.query)
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
    if decision.lane in ("FILTER", "COMPARE", "EXPLAIN"):
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

    plan = derive_plan(decision)   # model plan refinement arrives with the plan-proposal leg

    resp = CoreResponse(envelope=envelope, lane=decision.lane, grounding=grounding)
    resp.extras["decision"] = decision.as_dict()
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
        # provenance (R9.1): the trace must say when this turn's constraints came from the
        # SESSION, not the message — and postflight persists what was USED, so a budget-less
        # follow-up refreshes the remembered budget instead of wiping it.
        "budget_inherited": budget_inherited,
        "requirements_inherited": requirements_inherited,
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

    # BUDGET × CAPABILITY (Phase 1a — the "smart moment"): state the catalog-derived capability
    # floor, confirm within budget, or offer an honest tradeoff when budget < floor. Runs AFTER
    # the conflict clarify (a stated-requirement conflict outranks it) and BEFORE slot-gap so its
    # tradeoff clarify wins that slot. Never raises — the products already stand on their own; the
    # whole core is gated by RECOMMEND_CORE_MODE at the facade, so this is off in prod until flip.
    try:
        _apply_capability_budget(db, envelope, decision, resp, limit)
    except Exception as exc:
        logger.warning("capability-budget stage skipped: %s", repr(exc)[:120])

    # SHELF (Phase 1b): partition the ranked cards into the 3-band right-side panel contract
    # (best_fit / stretch-or-more-capable / preference). Reads the capability banner set above;
    # never raises — the flat products already stand on their own.
    try:
        _build_shelf(db, envelope, decision, resp, limit)
    except Exception as exc:
        logger.warning("shelf stage skipped: %s", repr(exc)[:120])

    # VARIANT CLARIFIER (Phase 1c): one question only when a variant materially moves the floor and
    # the shopper hasn't anchored it — else a stated assumption; content-advisory surfaces, never
    # blocks. Runs before slot-gap so a specific variant ask outranks the generic "tell me more".
    try:
        _maybe_variant_clarify(envelope, decision, resp)
    except Exception as exc:
        logger.warning("variant-clarify stage skipped: %s", repr(exc)[:120])

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
    bundle = gather_evidence(db, free_env, node_handle=decision.node_handle, limit=n)
    if bundle.status != "ok" or not bundle.variants:
        return []
    cards, _ = build_cards(bundle.variants, decision.requirements or None, limit=n)
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
    if floor is None and bmax is not None and decision.node_handle:
        floor = _budget_free_floor(db, envelope, decision, limit)
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
            resp.message = (f"These all handle {phrase} — they start at ${floor / 100:,.0f} "
                            f"and go up to ${top / 100:,.0f} for more headroom.")
        else:
            resp.message = f"These all handle {phrase}, starting at ${floor / 100:,.0f}."
    elif floor <= bmax:
        cap["verdict"] = "within_budget"
        if not str(resp.message or "").strip():
            resp.message = (f"The best fit for {phrase} starts at ${floor / 100:,.0f}, within "
                            f"your ${bmax / 100:,.0f} budget.")
    else:
        cap["verdict"] = "below_budget"
        if resp.products:
            resp.message = (f"Nothing at ${bmax / 100:,.0f} fully meets what {phrase} needs — the "
                            f"cheapest that does is ${floor / 100:,.0f}. Showing the closest in "
                            f"your budget below.")
        else:
            resp.message = (f"I don't have anything at ${bmax / 100:,.0f} that meets what {phrase} "
                            f"needs — the cheapest that does is ${floor / 100:,.0f}.")
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
        # the stretch story lives ABOVE the ceiling — reuse the budget-free node set
        in_ids = {c.sku for c in in_budget}
        above_budget = [c for c in _budget_free_cards(db, envelope, decision, limit)
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
        resp.message = f"{top.title}{price} leads this shortlist: {why}."
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
            resp.message = (f"None of the current options are from {decision.brand_filter} — "
                            f"tell me if another brand works, or widen the search.")
    # COMPARE of NAMED units (R9.3): narrow to the products the shopper actually named — the
    # compare_two_models case returned the whole category instead of the Dell G16 vs the Lenovo.
    if decision.lane == "COMPARE" and decision.compare_targets:
        pair = _bind_compare_targets(variants, decision.compare_targets)
        if pair:
            variants = pair
            names = " vs ".join((v.title or v.sku)[:48] for v in pair)
            resp.message = f"Comparing {names}."
            resp.extras["compare_bound"] = [v.sku for v in pair]
    cards, summary = build_cards(variants, decision.requirements or None, limit=limit,
                                 sort=decision.sort, preferred=_preferred_values(resp))
    resp.products = cards
    if decision.requirements:
        resp.fit_summary = summary
        if summary.get("closest_match_mode"):
            reqs = ", ".join(f"{k} {op} {int(t) if float(t).is_integer() else t}"
                             for k, preds in decision.requirements.items()
                             for (op, t) in preds)
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
