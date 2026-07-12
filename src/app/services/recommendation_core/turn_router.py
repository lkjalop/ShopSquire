"""Turn router (V2 Phase 4, step 3) — the semantic router REGROUNDED.

The 2026-07-10 router failed because it read a `capabilities.sells` list no profile declared:
the clamp was a no-op and the MODEL decided membership. This version is grounded end-to-end:

  model's role   — map unbounded language to (lane, taxonomy handle, requirements): what its
                   training knows ('A100' is a datacenter GPU; 'valorant at 144fps' implies a
                   refresh floor) applied to a CLOSED candidate list from the pinned taxonomy.
  platform's role— every model output crosses a deterministic clamp:
                   • lane must be in LANES;
                   • the handle must come from the OFFERED candidates (registry-real by
                     construction — same clamp as the classifier);
                   • OFF_CATALOG is honored ONLY when evidence.refusal_allowed() ==
                     sells_within()==False — the model may PROPOSE a refusal, only the sold
                     set can GRANT one (ungrounded/error ⇒ downgrade to SEARCH, never refuse);
                   • requirements are clamped to attribute-registry KEYS, known OPS, numeric
                     thresholds within the def's sanity bounds.
  failure mode   — any miss (bad JSON, foreign handle, timeout) → deterministic default:
                   lane=SEARCH, no handle, no requirements. Degradation, never invention.

Model resolution deliberately ignores OLLAMA_SMALL/DEFAULT (vision-typed in real deployments
— the VL-chain lesson): ROUTER_MODEL → CLASSIFIER_MODEL → certified text default.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.app.services.attribute_registry import defs_union
from src.app.services.catalog_classifier import candidate_nodes
from src.app.services.recommendation_core.envelope import LANES, TurnEnvelope
from src.app.services.recommendation_core.evidence import refusal_allowed
from src.app.services.recommendation_core.fit import DEFAULT_VERTICALS
from src.app.services.taxonomy_registry import get_node, primary_sold_node, sells_within, sold_nodes

logger = logging.getLogger("shopsquire.recommendation_core.turn_router")


def _reroute_host_node(db, envelope: TurnEnvelope, relationship: str) -> Optional[str]:
    """The DEVICE a named workload runs on (M3-C1 / review-8 #3). The OLD reroute target was
    'most-classified sold node', which GPT-5.6 showed can be PHARMACY or accessories for a mixed
    catalog ('play valorant' → 10 hand-sanitiser SKUs). Now: the store profile DECLARES the hosts
    (capability_host_nodes[relationship], e.g. run_on → [Gaming Laptops, Laptops]); the model
    picks the relationship, deterministic policy picks a device ONLY from declared hosts (clamped
    to real + not-explicitly-unsold). Fall back to primary_sold_node ONLY when the profile
    declares none — with a warning, since that fallback is the known-imperfect path."""
    try:
        from src.app.platform.store_profile import profile_slot
        hosts = (profile_slot("capability_host_nodes", default={}) or {}).get(relationship) or []
        for h in hosts:
            n = get_node(str(h))
            # require a GROUNDED, sellable host (is True, not just "not False"): on an ungrounded
            # tenant sells_within is None → we do NOT confidently reroute (fall through to the
            # primary_sold_node path, which itself returns None ungrounded → broad search).
            if n is not None and sells_within(db, n.handle, tenant_id=envelope.tenant_id) is True:
                return n.handle
        if hosts:
            logger.debug("declared capability hosts not sellable/grounded; trying primary_sold_node")
    except Exception as exc:
        logger.debug("capability_host_nodes lookup failed: %s", repr(exc)[:100])
    host = primary_sold_node(db, tenant_id=envelope.tenant_id)
    if host is not None:
        logger.info("workload reroute used primary_sold_node fallback (no declared host): %s", host)
    return host

LLMFn = Callable[[str, float], str]
_ALLOWED_OPS = (">=", "<=", ">", "<", "==")
# Software (so) and Media (me) are WORKLOAD/CONTENT verticals — you run/play them on a
# device, you don't buy them AS the device. Routing here = a use-case signal, never a
# product-gap refusal. Vertical-blind (no game/app names). Handle prefixes: 'so', 'so-…',
# 'me', 'me-…'.
import re as _re
_WORKLOAD_RE = _re.compile(r"^(so|me)(-|$)")
# a capability verb signals 'device to run/use X' (not 'buy X') — the purchase-vs-capability
# disambiguator for software/media routes (review #4). Small, principled, vertical-blind.
_CAPABILITY_VERB_RE = _re.compile(
    r"\b(play|playing|run|running|edit|editing|render|rendering|stream|streaming|"
    r"develop|development|train|training)\b|\bfor\s+\w", _re.IGNORECASE)


def _number_has_size_unit(query: str, value: float) -> bool:
    """Does the query state `value` next to a storage/memory unit? '1TB'→1000, '1000gb'→1000,
    '16 gb'→16. Guards the budget-bleed clamp from dropping a GENUINE spec (review #3)."""
    q = str(query or "").lower()
    v = int(value) if float(value).is_integer() else value
    tb = v / 1000 if v >= 1000 else None   # 1000 GB expressed as '1tb'
    pats = [rf"\b{v}\s*(gb|tb|g|t)\b"]
    if tb and float(tb).is_integer():
        pats.append(rf"\b{int(tb)}\s*tb\b")
    return any(_re.search(p, q) for p in pats)


def _router_model() -> str:
    return (os.getenv("ROUTER_MODEL") or os.getenv("CLASSIFIER_MODEL") or "qwen3:14b")


def _default_llm_fn(prompt: str, timeout: float) -> str:
    try:
        import httpx
        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = _router_model()
        payload = {"model": model, "prompt": prompt, "stream": False, "format": "json",
                   "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                   "options": {"temperature": 0, "num_predict": 256}}
        if "qwen3" in model.lower():
            payload["think"] = False
        r = httpx.post(f"{url}/api/generate", json=payload, timeout=max(2.0, float(timeout or 12.0)))
        data = r.json() or {}
        if r.status_code != 200 or data.get("error"):
            logger.warning("router model call failed: http=%s error=%s model=%s",
                           r.status_code, str(data.get("error"))[:120], model)
            return ""
        return str(data.get("response", "") or "")
    except Exception as exc:
        logger.warning("router model call failed: %s model=%s", repr(exc)[:120], _router_model())
        return ""


def _query_names_sold_category(db, envelope: TurnEnvelope) -> bool:
    """Does the query contain a SOLD node's own name-token (plural-forgiving)?
    'laptop for fine-tuning LLMs' names Laptops → sold → refusal vetoed;
    'do you sell forklifts?' names nothing sold → veto does not apply."""
    try:
        from src.app.services.catalog_classifier import _plural_expand, _tokens
        from src.app.services.taxonomy_registry import get_node, sold_nodes
        sold = sold_nodes(db, tenant_id=envelope.tenant_id)
        if not sold:
            return False
        q_toks = _plural_expand(set(_tokens(envelope.query)))
        for handle in sold:
            n = get_node(handle)
            if n and (set(_tokens(n.name)) & q_toks):
                return True
        return False
    except Exception:
        return False  # veto is a safety refinement; its failure must not block routing


@dataclass(frozen=True)
class TurnDecision:
    lane: str = "SEARCH"
    node_handle: Optional[str] = None            # clamped to offered candidates
    node_path: Optional[str] = None
    # key -> [(op, thr), ...] — a predicate LIST so a range (floor AND ceiling) is one value
    # end-to-end (M2-B1); the router itself emits one predicate per key (the model's clamp).
    requirements: Dict[str, List[Tuple[str, float]]] = field(default_factory=dict)
    use_cases: Tuple[str, ...] = ()              # model-classified, clamped to KB keys
    refusal_granted: bool = False                # sells_within()==False confirmed the refusal
    confidence: float = 0.0
    source: str = "model"                        # model | default
    # TWO-SLOT INTENT (M3-C1): the shopper's message carries a DEVICE they want to buy and,
    # separately, WORKLOADS they'll run on it. 'play valorant on a laptop' = device Laptops +
    # workload Video-Game-Software, relationship run_on. Derived deterministically from the
    # routed node's vertical (so-/me- = a workload, not a device); node_handle stays the
    # retrieval target (rerouted to the device for a run_on turn).
    requested_product_node: Optional[str] = None   # the DEVICE to retrieve (== node_handle)
    workloads: Tuple[str, ...] = ()                # content/software nodes named as workloads
    relationship: str = "buy"                      # buy (named a product) | run_on (named a workload)
    # SESSION (M3-C2): the prior turn's shortlist SKUs. CONSUMED since R9.4 (review-6 #17
    # closed): an EXPLAIN/COMPARE turn whose subject came from the session retrieves exactly
    # these SKUs in shown order ('the first one' = cards[0] of what the shopper actually saw).
    prior_shortlist: Tuple[str, ...] = ()
    # REFINEMENTS (R9.2 — the FILTER-executor slots): the model NAMES the narrowing, clamps
    # keep it grounded — brand must be a REAL catalog brand (case-insensitive → canonical DB
    # casing), sort ∈ ranking.SORTS. A miss drops the refinement, never invents one.
    brand_filter: Optional[str] = None
    sort: Optional[str] = None
    # R9.4: True when the routed node came from the SESSION (nodeless-continuation inherit or
    # fragment-drift override) — the turn is ABOUT the prior subject, so EXPLAIN/COMPARE may
    # consume prior_shortlist ('the first one' = the items actually shown last turn).
    subject_from_session: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"lane": self.lane, "node_handle": self.node_handle, "node_path": self.node_path,
                "requirements": {k: [list(p) for p in v] for k, v in self.requirements.items()},
                "use_cases": list(self.use_cases), "refusal_granted": self.refusal_granted,
                "confidence": round(self.confidence, 3), "source": self.source,
                "requested_product_node": self.requested_product_node,
                "workloads": list(self.workloads), "relationship": self.relationship,
                "prior_shortlist": list(self.prior_shortlist),
                "brand_filter": self.brand_filter, "sort": self.sort,
                "subject_from_session": self.subject_from_session}


DEFAULT_DECISION = TurnDecision(source="default")


def _clamp_brand(db, raw: Any) -> Optional[str]:
    """Model-named brand → the CATALOG's canonical casing, or None. The clamp is the catalog
    itself (distinct non-null brands) — an invented/unstocked brand is dropped, never guessed."""
    b = str(raw or "").strip().lower()
    if not b or db is None:
        return None
    try:
        from sqlalchemy import text as _t
        rows = db.execute(_t("SELECT DISTINCT brand FROM products "
                             "WHERE brand IS NOT NULL AND brand != ''")).fetchall()
        for (name,) in rows:
            if str(name).strip().lower() == b:
                return str(name)
    except Exception as exc:
        logger.debug("brand clamp lookup failed: %s", repr(exc)[:100])
    return None


def _stocked_handles(db, tenant_id: str, handles: List[str]) -> frozenset:
    """Which candidate handles would actually retrieve catalog products (R8.2): the handle sits
    WITHIN a sold subtree (an ancestor-or-self is granted) OR a sold node sits within ITS subtree
    (retrieval reads the node's subtree, so it contains stock). Pure string-prefix over ONE
    sold_nodes() read — ancestry is handle-encoded. Empty set when ungrounded: no markers beat
    wrong markers. This is an ANNOTATION for the model's judgment, never a gate — the refusal
    gate (sells_within) stays the authority."""
    try:
        sold = sold_nodes(db, tenant_id=tenant_id)
    except Exception:
        sold = None
    if not sold:
        return frozenset()
    out = set()
    for h in handles:
        if any(h == s or h.startswith(s + "-") or s.startswith(h + "-") for s in sold):
            out.add(h)
    return frozenset(out)


def _build_prompt(envelope: TurnEnvelope, cands: List, req_keys: List[str],
                  use_case_keys: List[str], stocked: frozenset = frozenset()) -> str:
    # [in catalog] = platform truth beside each candidate (R8.2 — the bag→sleeve mis-ground:
    # semantically interchangeable siblings need the sold signal to break the tie; without it the
    # model guessed Laptop Sleeves (empty) over Laptop Bags (stocked, top-scored)).
    lines = "\n".join(f"  {n.handle} : {n.full_path}{'  [in catalog]' if n.handle in stocked else ''}"
                      for n, _ in cands) or "  (none)"
    # BUDGET CONTEXT (budget-bleed structural fix): the price is stated to the model so it is
    # NEVER parsed as a spec ('under $1500' → storage_gb>=1500 was the live bug). The platform
    # already applies budget; the model must not return it as a requirement.
    budget_note = ""
    if envelope.budget_max_cents is not None or envelope.budget_min_cents is not None:
        lo = f"${envelope.budget_min_cents//100}" if envelope.budget_min_cents else "any"
        hi = f"${envelope.budget_max_cents//100}" if envelope.budget_max_cents else "any"
        budget_note = (f"BUDGET: {lo}–{hi} (already applied by the platform — NEVER return a "
                       f"price as a requirement/spec).\n")
    return (
        "You are the routing brain of a commerce assistant. Classify the shopper's message.\n\n"
        f'MESSAGE: "{envelope.query[:400]}"\n'
        f"{budget_note}\n"
        f"LANES (pick exactly one): {', '.join(LANES)}\n"
        f"CANDIDATE CATEGORIES (pick the handle that best matches WHAT THE SHOPPER WANTS, "
        f"from this list only, or null):\n{lines}\n\n"
        "Rules:\n"
        "- The category is what they WANT TO BUY/ASK ABOUT — use your product knowledge "
        "(an 'A100 server' is a datacenter computer server; a laptop 'with A100-like "
        "performance' is a LAPTOP described by a spec).\n"
        "- OFF_CATALOG only when the wanted category is clearly not something this kind of "
        "store sells; the platform verifies against the real sold list either way.\n"
        "- When SEVERAL candidates plausibly fit the same want (bag vs sleeve vs case), prefer "
        "one marked [in catalog] — unmarked categories exist in the taxonomy but this store "
        "does not stock them. If what the shopper wants is clearly an UNMARKED category, still "
        "pick it (the platform answers honestly about stock).\n"
        "- A game, app, or workload implies the DEVICE CATEGORY that runs it — a competitive "
        "shooter implies gaming laptops/computers: pick that handle, not null.\n"
        "- USE_CASES: classify what the shopper will DO with it — pick 0, 1, or MORE from this "
        f"list (a persona/task/game/software maps here): {', '.join(use_case_keys)}. "
        "'CS student' + 'gaming' can BOTH apply; 'english essays' → university; 'AutoCAD' → "
        "engineering_student; 'video editing/rendering' → creative; 'run/train models' → "
        "ai_ml_workstation. The platform looks up each use-case's hardware requirements — you "
        "only NAME them.\n"
        "- Extract NUMERIC requirements the message EXPLICITLY states "
        f"(keys ONLY from: {', '.join(sorted(req_keys))}; e.g. '144fps' → refresh_hz≥144). "
        "Do NOT invent workload specs — that is what use_cases are for.\n"
        "- REFINE: if the shopper narrows to a BRAND ('only Asus', 'a Dell one') set "
        "refine.brand; if they ask for cheaper/most affordable set refine.sort=\"price_asc\"; "
        "premium/high-end → \"price_desc\". Both null when the message says neither.\n"
        '- POLICY_QUESTION for services (payment plans, delivery, returns policy).\n\n'
        'Return JSON: {"lane": "<lane>", "handle": "<candidate handle or null>", '
        '"use_cases": ["<key>", ...], '
        '"requirements": {"<key>": ["<op one of >=,<=,>,<,==>", <number>]}, '
        '"refine": {"brand": "<brand or null>", "sort": "price_asc|price_desc|null"}, '
        '"confidence": <0.0-1.0>}\nJSON:'
    )


def route_turn(db, envelope: TurnEnvelope, *, llm_fn: Optional[LLMFn] = None,
               timeout: float = 20.0) -> TurnDecision:
    """One model judgment, four deterministic clamps, one grounded refusal gate.
    Never raises; every failure path is the deterministic default (SEARCH, ungated)."""
    if not envelope.query:
        return DEFAULT_DECISION
    try:
        cands = candidate_nodes(envelope.query)
    except Exception:
        cands = []
    defs = defs_union(DEFAULT_VERTICALS)
    fit_keys = [k for k, d in defs.items() if d.kind == "quantity"]
    from src.app.services.recommendation_core.intent_resolver import known_use_cases
    fn = llm_fn or _default_llm_fn
    stocked = _stocked_handles(db, envelope.tenant_id, [n.handle for n, _ in cands])
    try:
        raw = fn(_build_prompt(envelope, cands, fit_keys, known_use_cases(), stocked), timeout)
        data = json.loads(raw) if raw else None
    except Exception:
        data = None
    if not isinstance(data, dict):
        return DEFAULT_DECISION

    # clamp 1: lane ∈ LANES
    lane = str(data.get("lane") or "").strip().upper()
    if lane not in LANES:
        return DEFAULT_DECISION
    # clamp 2: handle must be REGISTRY-REAL. Deliberately looser than the classifier's
    # candidates-only clamp: queries name INTENTS, not product titles — 'do you sell
    # forklifts?' has zero token overlap with 'Material Handling', so the true node is often
    # unofferable and the model's world knowledge IS the mapping. Safety does not depend on
    # this clamp: a refusal still requires sells_within()==False (clamp 4), and for SEARCH a
    # wrong-ish handle is only a retrieval hint. Candidates stay in the prompt as guidance.
    node = get_node(str(data.get("handle") or "").strip())
    # SESSION CONSUMPTION (M3-C2): make multi-turn REAL. A CONTINUATION turn — the model
    # classified it FILTER/COMPARE/EXPLAIN (narrowing / comparing / asking-about, not a fresh
    # SEARCH) and named NO node of its own — is refining the PRIOR subject, so inherit the last
    # turn's node: 'only the 16GB ones' filters the last search, 'why is the first one better'
    # asks about the last shortlist. The MODEL's lane is the signal (no anaphora regex); the
    # prior node was already sellability-checked last turn. Prior REQUIREMENTS are deliberately
    # NOT auto-merged — that is the context-rot class (a gaming-era spec hard-filtering a later
    # work-laptop turn); the fragment's own requirements still extract below.
    session = envelope.session or {}
    prior_shortlist = tuple(str(s) for s in (session.get("shortlist_skus") or [])[:12])
    subject_from_session = False
    if lane in ("FILTER", "COMPARE", "EXPLAIN"):
        pn = get_node(str(session.get("prior_node") or ""))
        if node is None:
            if pn is not None:
                node = pn
                subject_from_session = True
        elif pn is not None:
            # FRAGMENT-DRIFT GUARD (R9.2 live finding): 'show me cheaper ONES' embedding-matched
            # Swimwear > One-Pieces — a continuation fragment that accidentally grounds to an
            # UNRELATED node would silently pivot the whole subject ($45 swimsuits after a
            # gaming-laptop turn). A CONTINUATION lane by definition refines the prior subject,
            # so the model's node stands only when it is prior-RELATED: ancestor/descendant OR
            # the same depth-1 family (≥2 shared leading handle segments — Laptops→Gaming
            # Laptops is a legitimate 'the gaming ones' refinement inside Computers; Swimwear
            # shares nothing with Electronics). Unrelated → the prior node wins. A genuine
            # category pivot classifies as SEARCH, not FILTER, so this never blocks it.
            h, p = node.handle, pn.handle
            hs, ps = h.split("-"), p.split("-")
            common = 0
            for a, b in zip(hs, ps):
                if a != b:
                    break
                common += 1
            related = (h == p or h.startswith(p + "-") or p.startswith(h + "-") or common >= 2)
            if not related:
                logger.info("continuation fragment drifted (%s → %s); keeping prior subject",
                            lane, node.handle)
                node = pn
                subject_from_session = True
    # clamp 3: requirements — known keys, known ops, numeric, within sanity bounds
    requirements: Dict[str, List[Tuple[str, float]]] = {}
    for key, spec in (data.get("requirements") or {}).items():
        d = defs.get(str(key))
        if d is None or d.kind != "quantity" or not isinstance(spec, (list, tuple)) or len(spec) != 2:
            continue
        op, thr = str(spec[0]), spec[1]
        if op not in _ALLOWED_OPS or not isinstance(thr, (int, float)) or isinstance(thr, bool):
            continue
        if d.bounds and not (d.bounds[0] <= float(thr) <= d.bounds[1]):
            continue
        # BUDGET-BLEED GUARD (review-8 root-cause 1 — the 39.4% storage-fail class): a GB-unit
        # spec (storage_gb / ram_gb / gpu_vram_gb) is only real when the query states that number
        # WITH a size unit. '$1200-$1800' → storage_gb>=1200 was the live bug — the model reads a
        # PRICE as a spec, and the old guard only caught it when a STRUCTURED budget happened to
        # equal the value (empty for natural-language budgets like the corpus). Now: REQUIRE the
        # unit unconditionally for these keys. '1TB laptop under $1000' → storage_gb 1000 stays
        # (the query says '1tb'); '$1800' → storage_gb 1800 is dropped (no '1800gb' in the query).
        if (d.key in ("storage_gb", "ram_gb", "gpu_vram_gb")
                and not _number_has_size_unit(envelope.query, thr)):
            continue
        requirements[d.key] = [(op, float(thr))]
    # clamp 3b: use_cases — clamp each to a real KB key (normalize aliases; drop unknowns)
    from src.app.services.recommendation_core.intent_resolver import normalize_use_case
    use_cases: List[str] = []
    for uc in (data.get("use_cases") or []):
        n = normalize_use_case(str(uc))
        if n and n not in use_cases:
            use_cases.append(n)
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0

    # REFINEMENTS clamp (R9.2): sort ∈ the closed ranking vocabulary; brand ∈ the catalog's
    # real brands (canonical casing). A miss drops the refinement — never invent a narrowing.
    from src.app.services.recommendation_core.ranking import SORTS
    refine = data.get("refine") if isinstance(data.get("refine"), dict) else {}
    sort = str(refine.get("sort") or "").strip().lower() or None
    if sort not in SORTS:
        sort = None
    brand_filter = _clamp_brand(db, refine.get("brand"))

    # clamp 4 — THE REFUSAL GATE, both directions. The model MAPS; the PLATFORM decides:
    # a purchase-ish turn whose routed node fails sells_within() is refused even if the
    # model hedged the lane to SEARCH (live finding: it mapped forklifts→Material Handling
    # perfectly, then hedged — it cannot know what the store sells, so it shouldn't decide);
    # and a proposed OFF_CATALOG without a granted node is NEVER honored.
    #
    # WRONGFUL-REFUSAL GUARD (shadow census 2026-07-11: 'only ones with 16GB RAM or more'
    # got refused): FILTER-lane turns are context-NARROWING fragments about a PRIOR subject
    # — a platform-elevated refusal there rides a mis-mapped fragment, never grant it.
    # (An earlier requirements-based proxy for this guard blocked CORRECT procurement
    # refusals — 'five A100 servers' extracts count>=5 — the lane is the real signal.)
    # C2-KEEP (M3-C2): session consumption now RESOLVES the multi-turn version (a FILTER
    # continuation inherits the prior sold node above, so its refusal check passes anyway). But
    # this guard is ALSO the COLD-START floor — a shopper's FIRST message being a bare filter
    # fragment has no prior node to inherit, and refusing that mis-mapped fragment is still
    # wrong. The guard is an independent invariant, not a pure session proxy → it STAYS
    # (over-excision is the risk; ledger §8).
    # WORKLOAD-VERTICAL GUARD (GPT-5.6 review-3 #6, valorant 2/3 regression, STRUCTURAL not a
    # game regex): the model correctly maps 'play valorant at 144fps' → so-3-1 (Software >
    # Video Game Software). But Software (so) and Media (me) are things you RUN ON a device,
    # not the device — the shopper named a WORKLOAD, not a product to buy. Routing there is a
    # use-case signal: never refuse, drop the content node so retrieval does DEVICE search,
    # keep the implied requirements (refresh_hz>=144). Vertical-blind: a forklift (bi) is NOT
    # a workload vertical and stays correctly refusable.
    # CAPABILITY SIGNAL (review #4): only treat a software/media route as a WORKLOAD (device to
    # run it) when the shopper expressed a capability — a use-case, extracted requirements, or a
    # capability verb ('play/run/for/edit/render/stream/develop/train'). A BARE purchase ask
    # ('do you sell Photoshop licenses?', 'do you stock PS5 games?') has none of these, so the
    # software node STANDS and the refusal gate answers honestly ('we don't stock that + RFQ').
    # TWO-SLOT REROUTE (M3-C1): the OLD code set node=None here, losing the device category —
    # 'play valorant at 144fps' then did a broad LIKE-search on the prose ('nothing meets'),
    # while 'gaming laptop for valorant' worked. The named workload IS a use-case signal; the
    # device that runs it is the store's PRIMARY SOLD category. Record the workload
    # (relationship=run_on) and REROUTE retrieval to that device node — a real catalog leg, not
    # a broad miss. Vertical-blind: the reroute target is 'most-classified sold node', furniture/
    # pharma-agnostic; a forklift (bi) is not a workload vertical and never reaches here.
    workloads: List[str] = []
    relationship = "buy"
    if node is not None and _WORKLOAD_RE.match(node.handle):
        capability = bool(requirements) or bool(use_cases) or _CAPABILITY_VERB_RE.search(envelope.query)
        if capability:
            workloads.append(node.handle)
            relationship = "run_on"
            host = _reroute_host_node(db, envelope, "run_on")
            node = get_node(host) if host else None   # reroute to the device (None only if ungrounded)
            if lane == "OFF_CATALOG":
                lane = "SEARCH"
        # else: leave the software/media node in place → refusal gate decides honestly

    model_proposed_refusal = (lane == "OFF_CATALOG")
    refusal_granted = False
    # PROCUREMENT is in the gate lanes deliberately (census: '$80k A100 servers' routed as
    # PROCUREMENT — truthfully — and skipped honesty): procuring an UNSOLD category IS the
    # off-catalog case, and the off-catalog answer already carries the supplier-RFQ offer,
    # which is exactly the right procurement response.
    if node is not None and lane in ("SEARCH", "FILTER", "COMPARE", "EXPLAIN", "OFF_CATALOG",
                                     "PROCUREMENT"):
        if model_proposed_refusal or lane != "FILTER":
            refusal_granted = refusal_allowed(db, node.handle, tenant_id=envelope.tenant_id)
    # SOLD-NAME VETO (census: 'laptop for fine-tuning LLMs' — no numbers, model itself
    # proposed refusal via datacenter-thinking; but the query NAMES 'laptop', a sold
    # category). The sold set that GRANTS refusals also VETOES them: a query naming a sold
    # category's own name-token can never be refused, whatever the model mapped. Symmetric,
    # deterministic, grounded — no model opinion involved.
    if refusal_granted and _query_names_sold_category(db, envelope):
        refusal_granted = False
    if refusal_granted:
        lane = "OFF_CATALOG"
    elif lane == "OFF_CATALOG":
        lane = "SEARCH"       # ungrounded/unknown/actually-sold → NEVER refuse

    return TurnDecision(lane=lane, node_handle=(node.handle if node else None),
                        node_path=(node.full_path if node else None),
                        requirements=requirements, use_cases=tuple(use_cases),
                        refusal_granted=refusal_granted, confidence=conf, source="model",
                        requested_product_node=(node.handle if node else None),
                        workloads=tuple(workloads), relationship=relationship,
                        prior_shortlist=prior_shortlist,
                        brand_filter=brand_filter, sort=sort,
                        subject_from_session=subject_from_session)
