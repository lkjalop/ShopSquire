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
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.app.services.attribute_registry import defs_union
from src.app.services.catalog_classifier import candidate_nodes
from src.app.services.recommendation_core.envelope import LANES, TurnEnvelope
from src.app.services.recommendation_core.evidence import refusal_allowed
from src.app.services.recommendation_core.fit import DEFAULT_VERTICALS
from src.app.services.taxonomy_registry import (get_node, primary_sold_node, search_nodes,
                                                sells_within, sold_nodes)

logger = logging.getLogger("shopsquire.recommendation_core.turn_router")

# Model-facing synonyms for the one bounded procurement lane. These are aliases, not new
# capabilities: the facade still delegates PROCUREMENT to the established fulfillment path.
_LANE_ALIASES = {
    "BULK": "PROCUREMENT",
    "BULK_QUOTE": "PROCUREMENT",
    "QUOTE": "PROCUREMENT",
    "RFQ": "PROCUREMENT",
}


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
        # P1 latency lever: the router emits a compact JSON decision — capping generated tokens cuts
        # the dominant model time. Configurable so an 8B (better routing quality) can fit the p95 gate
        # by generating less, rather than dropping to a dumber model. 192 covers the bounded
        # schema with headroom; sealed replay guards against truncation-induced fallback.
        try:
            _num_predict = int(os.getenv("ROUTER_NUM_PREDICT", "320") or 320)
        except Exception:
            _num_predict = 320
        payload = {"model": model, "prompt": prompt, "stream": False, "format": "json",
                   "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                   "options": {"temperature": 0, "num_predict": _num_predict}}
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
    audience_contexts: Tuple[str, ...] = ()      # context only; never weakens workload floors
    use_case_variants: Dict[str, str] = field(default_factory=dict)  # use-case -> registry variant
    refusal_granted: bool = False                # sells_within()==False confirmed the refusal
    confidence: float = 0.0
    source: str = "model"                        # model | default
    # TWO-SLOT INTENT (M3-C1): the shopper's message carries a DEVICE they want to buy and,
    # separately, WORKLOADS they'll run on it. 'play valorant on a laptop' = device Laptops +
    # workload Video-Game-Software, relationship run_on. Derived deterministically from the
    # routed node's vertical (so-/me- = a workload, not a device); node_handle stays the
    # retrieval target (rerouted to the device for a run_on turn).
    requested_product_node: Optional[str] = None   # the DEVICE to retrieve (== node_handle)
    requested_category_label: Optional[str] = None  # buyer-facing label when taxonomy is approximate
    # Closed model signal for requests outside product commerce. It is advisory until the clamp
    # confirms there is no grounded product node; it can never suppress a catalog result.
    request_scope: str = "uncertain"               # product | service_or_place | uncertain
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
    # SOFT brand preference (Phase 1d) — distinct from the HARD brand_filter above: 'ideally a Mac'
    # must NOT remove non-Apple options, it should surface an Apple 'preference' band on the shelf.
    # Clamped to a real catalog brand; nulled when it equals a hard brand_filter (already narrowed).
    preferred_brand: Optional[str] = None
    # brand EXCLUSION ('a gaming laptop but NOT Apple') — the negation slot the V2 core was missing;
    # clamped to a real catalog brand, subtracted at retrieval AND from the capability floor.
    exclude_brand: Optional[str] = None
    # keep | set | clear. A separate operation is required because null brand fields mean
    # "not mentioned this turn" and must not also mean "remove remembered constraints".
    brand_action: str = "keep"
    # R9.4: True when the routed node came from the SESSION (nodeless-continuation inherit or
    # fragment-drift override) — the turn is ABOUT the prior subject, so EXPLAIN/COMPARE may
    # consume prior_shortlist ('the first one' = the items actually shown last turn).
    subject_from_session: bool = False
    # R9.3: the specific products the shopper NAMED in a compare ('the Dell G16 vs the Lenovo
    # Legion') — model-named short strings; the CORE binds each to a retrieved variant by
    # distinctive-token overlap and narrows only when ≥2 bind unambiguously (never guess a
    # comparison down to the wrong units). Empty = whole-category compare.
    compare_targets: Tuple[str, ...] = ()
    # BULK (Phase 1f — model-judged, not regex): the shopper's ORDER SIZE and TOTAL budget for a
    # bulk/procurement ask ('20 laptops … $16000 total'). Model EXTRACTS; the clamp bounds them to
    # sane values. quantity is a count, not a fit predicate; total_budget is the whole-order budget
    # (distinct from the per-unit budget the platform already applies at retrieval).
    quantity: Optional[int] = None
    total_budget_cents: Optional[int] = None
    # per_unit | total | unknown — whether a STATED budget is per-item or the whole-order total.
    # NEVER reinterpret a per-unit budget as a total (the arithmetic-safety invariant, review-10 P0).
    budget_scope: str = "unknown"
    # How the shopper expressed the maximum. It controls clarification/stretch presentation,
    # never authorization: the primary slate remains inside the cap for every mode.
    budget_cap_mode: str = "hard"          # hard | soft | ambiguous
    # continue | switch | uncertain (review-10 P0.2) — the model's LANE-INDEPENDENT continuation
    # signal; drives prior-subject inheritance and suppresses fragment-drift on an explicit switch.
    subject_action: str = "uncertain"

    def as_dict(self) -> Dict[str, Any]:
        return {"lane": self.lane, "node_handle": self.node_handle, "node_path": self.node_path,
                "requirements": {k: [list(p) for p in v] for k, v in self.requirements.items()},
                "use_cases": list(self.use_cases), "refusal_granted": self.refusal_granted,
                "audience_contexts": list(self.audience_contexts),
                "use_case_variants": dict(self.use_case_variants),
                "confidence": round(self.confidence, 3), "source": self.source,
                "requested_product_node": self.requested_product_node,
                "requested_category_label": self.requested_category_label,
                "request_scope": self.request_scope,
                "workloads": list(self.workloads), "relationship": self.relationship,
                "prior_shortlist": list(self.prior_shortlist),
                "brand_filter": self.brand_filter, "sort": self.sort,
                "preferred_brand": self.preferred_brand, "exclude_brand": self.exclude_brand,
                "brand_action": self.brand_action,
                "subject_from_session": self.subject_from_session,
                "compare_targets": list(self.compare_targets),
                "quantity": self.quantity, "total_budget_cents": self.total_budget_cents,
                "budget_scope": self.budget_scope, "budget_cap_mode": self.budget_cap_mode,
                "subject_action": self.subject_action}


DEFAULT_DECISION = TurnDecision(source="default")


def _bounded_fallback_decision(db, envelope: TurnEnvelope, cands, *, reason: str) -> TurnDecision:
    """Recover only platform-verifiable facts when model routing is unavailable.

    This path never invents requirements or use cases. It may select a registry-real,
    tenant-sold taxonomy candidate and recover an explicit quantity/budget scope with
    the shared grammars. The source remains a fallback so promotion metrics count it.
    """
    node = None
    for candidate, _score in cands:
        if sells_within(db, candidate.handle, tenant_id=envelope.tenant_id) is True:
            node = candidate
            break
    if node is None or not _query_names_sold_category(db, envelope):
        return TurnDecision(source=f"fallback:{reason}")

    from src.app.services.bulk_intent import extract_quantity_span
    from src.app.services.budget_grammar import classify_budget_scope, parse_budget

    unit_nouns = {
        segment.strip().lower()
        for candidate, _score in cands
        for segment in candidate.full_path.split(">")
        if segment.strip()
    }
    parsed_quantity = extract_quantity_span(envelope.query, unit_nouns=unit_nouns)
    quantity = parsed_quantity[0] if parsed_quantity is not None else None
    budget_scope = classify_budget_scope(envelope.query)
    total_budget_cents = None
    if budget_scope == "total":
        parsed_budget = parse_budget(envelope.query)
        if parsed_budget is not None and parsed_budget.budget_max is not None:
            total_budget_cents = int(parsed_budget.budget_max) * 100

    return TurnDecision(
        lane="PROCUREMENT" if quantity is not None and quantity >= 2 else "SEARCH",
        node_handle=node.handle,
        node_path=node.full_path,
        confidence=0.4,
        source=f"fallback:{reason}",
        requested_product_node=node.handle,
        quantity=quantity,
        total_budget_cents=total_budget_cents,
        budget_scope=budget_scope,
    )


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


def _explicitly_excluded_brand(db, query: str) -> Optional[str]:
    """Return a catalog brand named in an explicit exclusion phrase.

    The model owns semantic interpretation, but a clamped positive brand may not
    contradict an unambiguous buyer negation.  The vocabulary comes from the
    tenant catalog; this guard contains no merchant or vertical brand list.
    """
    q = " ".join(str(query or "").strip().lower().split())
    if not q or db is None:
        return None
    try:
        from sqlalchemy import text as _t
        rows = db.execute(_t(
            "SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand != ''"
        )).fetchall()
    except Exception as exc:
        logger.debug("brand exclusion lookup failed: %s", repr(exc)[:100])
        return None
    for (name,) in rows:
        canonical = str(name or "").strip()
        if not canonical:
            continue
        brand = _re.escape(canonical.lower())
        patterns = (
            rf"\b(?:no|not|except|excluding|exclude|without)\s+{brand}\b",
            rf"\b(?:no|nothing)\s+from\s+{brand}\b",
            rf"\banything\s+but\s+{brand}\b",
        )
        if any(_re.search(pattern, q) for pattern in patterns):
            return canonical
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


def _catalog_brand_anchor_nodes(db, tenant_id: str, query: str) -> tuple:
    """Approved taxonomy nodes for a catalog brand explicitly named by the buyer.

    This is catalog evidence, not an intent parser: the model still chooses the category.  The
    returned nodes only let the post-model clamp repair an unstocked category when one unique
    approved brand node also shares a product noun with the query.  That prevents persona words
    (for example, a school context) from turning a named stocked product into an unrelated toy,
    without teaching the core any merchant brands or product categories.
    """
    q = " ".join(str(query or "").strip().lower().split())
    if not q or db is None:
        return ()
    try:
        from sqlalchemy import text as _t
        brands = db.execute(_t(
            "SELECT DISTINCT brand FROM products "
            "WHERE brand IS NOT NULL AND brand != '' AND active=:active"
        ), {"active": True}).fetchall()
        named = []
        for (raw_brand,) in brands:
            brand = str(raw_brand or "").strip()
            if brand and _re.search(rf"\b{_re.escape(brand.lower())}\b", q):
                named.append(brand)
        if len(named) != 1 or _explicitly_excluded_brand(db, query):
            return ()
        rows = db.execute(_t(
            "SELECT DISTINCT pc.node_handle FROM product_classification pc "
            "JOIN products p ON p.sku=pc.sku "
            "WHERE pc.tenant_id=:tenant AND pc.status='approved' "
            "AND LOWER(p.brand)=:brand AND p.active=:active"
        ), {"tenant": str(tenant_id), "brand": named[0].lower(), "active": True}).fetchall()
    except Exception as exc:
        logger.debug("catalog brand anchor lookup failed: %s", repr(exc)[:120])
        return ()

    stop = {"and", "the", "for", "with", "from", "product", "products", "device", "devices"}
    query_tokens = set(_re.findall(r"[a-z0-9]+", q)) - stop
    anchors = []
    for (handle,) in rows:
        node = get_node(str(handle or ""))
        if node is None:
            continue
        node_tokens = set(_re.findall(r"[a-z0-9]+", node.name.lower())) - stop
        # Singular/plural normalization is sufficient here: this is a bounded corroboration
        # check beside the model, not a second semantic router.
        normalized_query = {token.rstrip("s") for token in query_tokens}
        normalized_node = {token.rstrip("s") for token in node_tokens}
        if normalized_query & normalized_node:
            anchors.append(node)
    return tuple(sorted({node.handle: node for node in anchors}.values(), key=lambda n: n.handle))


def _prior_context_block(prior: Optional[Dict[str, Any]]) -> str:
    """Multi-turn context (context-rot fix): show the classifier the PRIOR subject so a
    subject-dropping follow-up ('only 6 people, $19000', 'how many can I get?') stays in the same
    category instead of mis-routing on a stray word ('drawing class' → Art & Crafts). Model-judged:
    the model still decides continuation vs a genuinely new search; deterministic clamps unchanged."""
    if not prior or not prior.get("node_path"):
        return ""
    ucs = ", ".join(prior.get("use_cases") or []) or "general use"
    bud = f", budget ~${prior['budget_max_cents'] // 100:,}" if prior.get("budget_max_cents") else ""
    return (
        f"PRIOR TURN (the shopper is CONTINUING this conversation): they were shopping for "
        f"\"{prior['node_path']}\" for use-case(s) \"{ucs}\"{bud}. If the CURRENT message refines "
        f"that order (a quantity, a budget, a brand, a spec, 'how many', 'what about', 'actually "
        f"…'), classify it in the SAME category and keep the use-case — do NOT jump to a different "
        f"product just because a word matches. Only pick a DIFFERENT category if the shopper "
        f"clearly starts a new search. Set subject_action: 'continue' if this message refines the "
        f"PRIOR subject (adds a spec/quantity/budget, 'also', 'the class needs', 'make it N'), "
        f"'switch' if it is a genuinely new product search, 'uncertain' if unclear.\n\n")


def _build_prompt_legacy(envelope: TurnEnvelope, cands: List, req_keys: List[str],
                  use_case_keys: List[str], stocked: frozenset = frozenset(),
                  prior: Optional[Dict[str, Any]] = None) -> str:
    # [in catalog] = platform truth beside each candidate (R8.2 — the bag→sleeve mis-ground:
    # semantically interchangeable siblings need the sold signal to break the tie; without it the
    # model guessed Laptop Sleeves (empty) over Laptop Bags (stocked, top-scored)).
    lines = "\n".join(f"  {n.handle} : {n.full_path}{'  [in catalog]' if n.handle in stocked else ''}"
                      for n, _ in cands) or "  (none)"
    # BUDGET CONTEXT (budget-bleed structural fix): the price is stated to the model so it is
    # NEVER parsed as a spec ('under $1500' → storage_gb>=1500 was the live bug). The platform
    # already applies budget; the model must not return it as a requirement.
    budget_note = ""
    image_note = ""
    if envelope.budget_max_cents is not None or envelope.budget_min_cents is not None:
        lo = f"${envelope.budget_min_cents//100}" if envelope.budget_min_cents else "any"
        hi = f"${envelope.budget_max_cents//100}" if envelope.budget_max_cents else "any"
        budget_note = (f"BUDGET: {lo}–{hi} (already applied by the platform — NEVER return a "
                       f"price as a requirement/spec).\n")
    return (
        "You are the routing brain of a commerce assistant. Classify the shopper's message.\n\n"
        f"{_prior_context_block(prior)}"
        f'MESSAGE: "{envelope.query[:400]}"\n'
        f"{budget_note}{image_note}\n"
        f"LANES (pick exactly one): {', '.join(LANES)}\n"
        f"CANDIDATE CATEGORIES (pick the handle that best matches WHAT THE SHOPPER WANTS, "
        f"from this list only, or null):\n{lines}\n\n"
        "Rules:\n"
        "- The category is what they WANT TO BUY/ASK ABOUT — use your product knowledge "
        "(an 'A100 server' is a datacenter computer server; a laptop 'with A100-like "
        "performance' is a LAPTOP described by a spec).\n"
        "- OFF_CATALOG only when the wanted category is clearly not something this kind of "
        "store sells; the platform verifies against the real sold list either way.\n"
        "- A request to buy, quote, source, or ask whether the store sells a product is commerce, "
        "even when the exact category is absent: use OFF_CATALOG. If no handle fits, provide a "
        "non-null wanted_category naming the specific taxonomy-style leaf, including its parent "
        "noun when ambiguous and describing the product rather than an accessory. "
        "Only a non-product service/location request uses SEARCH with a null handle and confidence "
        "0. Do not return a null or invented lane.\n"
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
        "- REFINE: a HARD brand narrowing ('only Asus', 'just Dell') → refine.brand; a SOFT brand "
        "preference ('ideally a Mac', 'I'd prefer Lenovo') → refine.prefer_brand (keeps other "
        "options, just surfaces that brand); a brand EXCLUSION ('but not Apple', 'anything except "
        "HP') → refine.exclude_brand. cheaper/most affordable → refine.sort=\"price_asc\"; "
        "premium/high-end → \"price_desc\". null when the message says none.\n"
        "- COMPARE of SPECIFIC products ('the Dell G16 vs the Lenovo Legion'): list each named "
        "product as a short name in compare_targets. Empty list when comparing a whole "
        "category ('compare your gaming laptops').\n"
        "- BULK: if the shopper wants MULTIPLE units ('20 laptops', 'about 20', 'for 6 people') set "
        "quantity to that whole number. If they state a TOTAL budget for the whole order ('$16000 "
        "total', 'budget is $19000') set total_budget to that dollar amount. Do NOT put the count "
        "in requirements. When ANY budget is stated, set budget_scope: 'per_unit' ($X each / per "
        "laptop) or 'total' ($X for the whole order); null when unclear. quantity/total_budget null "
        "for a single item / no stated budget.\n"
        "- POLICY_QUESTION is for general service policy (payment plans, generic delivery or returns). "
        "When the prior subject is a procurement/order, RFQ drafts, supplier channels, requested "
        "delivery dates, quantities, budgets, MOQ blockers, and whether a supplier message was sent "
        "are PROCUREMENT. A statement that keeps or changes existing constraints is FILTER or "
        "PROCUREMENT, not POLICY_QUESTION.\n\n"
        'Return JSON: {"lane": "<lane>", "handle": "<candidate handle or null>", '
        '"wanted_category": "<short product category when handle is null, else null>", '
        '"request_scope": "product|service_or_place|uncertain", '
        '"use_cases": ["<key>", ...], '
        '"requirements": {"<key>": ["<op one of >=,<=,>,<,==>", <number>]}, '
        '"refine": {"brand": "<hard-filter brand or null>", '
        '"prefer_brand": "<soft-preference brand or null>", '
        '"exclude_brand": "<brand to EXCLUDE or null>", "sort": "price_asc|price_desc|null"}, '
        '"compare_targets": ["<named product>", ...], '
        '"quantity": <positive integer or null>, "total_budget": <dollars or null>, '
        '"budget_scope": "per_unit|total|null", '
        '"subject_action": "continue|switch|uncertain|null", '
        '"confidence": <0.0-1.0>}\nJSON:'
    )


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
        "REFINE: brand=hard-only, prefer_brand=soft, exclude_brand=negation, sort=price_asc, "
        "price_desc or null. brand_action=keep when brands are unmentioned, set when adding or "
        "replacing a brand constraint, clear only when the shopper explicitly removes all brand "
        "constraints. compare_targets contains only specifically named products.\n"
        "BULK: quantity is unit count; total_budget is whole-order dollars; budget_scope is "
        "per_unit, total or null. Never reinterpret per-unit as total. budget_cap_mode is hard "
        "for explicit limits, soft for approximate targets, ambiguous when the wording is unclear.\n"
        "Return ONLY this JSON shape (use null/empty values when absent): "
        '{"lane":"SEARCH","handle":null,"wanted_category":null,"request_scope":"uncertain",'
        '"use_cases":[],"audience_contexts":[],"use_case_variant":null,"requirements":{},'
        '"refine":{"brand":null,"prefer_brand":null,"exclude_brand":null,"sort":null,'
        '"brand_action":"keep"},'
        '"compare_targets":[],"quantity":null,"total_budget":null,"budget_scope":null,'
        '"budget_cap_mode":"hard","subject_action":null,"procurement_context":"none",'
        '"confidence":0.0}.\n')


def _build_prompt(envelope: TurnEnvelope, cands: List, req_keys: List[str],
                  use_case_keys: List[str], stocked: frozenset = frozenset(),
                  prior: Optional[Dict[str, Any]] = None) -> str:
    """Compact dynamic suffix over a cacheable instruction prefix (latency P0)."""
    # Keep the semantic shortlist compact, but never trim away a catalog-grounded candidate.
    # This reduces prefill without weakening the sold-sibling signal that prevents empty-node drift.
    prompt_cands = list(cands[:12])
    for candidate in cands[12:]:
        if candidate[0].handle in stocked and candidate not in prompt_cands:
            prompt_cands.append(candidate)
        if len(prompt_cands) >= 16:
            break
    lines = "\n".join(
        f"  {node.handle} : {node.full_path}{' [in catalog]' if node.handle in stocked else ''}"
        for node, _ in prompt_cands
    ) or "  (none)"
    context = ""
    if prior and (prior.get("node_path") or prior.get("lane")):
        use_cases = ",".join(prior.get("use_cases") or []) or "general"
        prior_budget = (f"; budget_max=${prior['budget_max_cents']//100}"
                        if prior.get("budget_max_cents") else "")
        prior_lane = str(prior.get("lane") or "").strip().upper()
        lane_context = f"; active_lane={prior_lane}" if prior_lane else ""
        prior_subject = prior.get("node_path") or "current product/order"
        context = (f"PRIOR TURN: category={prior_subject}; use_cases={use_cases}"
                   f"{prior_budget}{lane_context}. "
                   "Set subject_action=continue for a refinement, switch for a new product, "
                   "uncertain otherwise. A continuation retains the prior subject. When the active "
                   "lane is PROCUREMENT, questions about the current order's quantity, sourcing, "
                   "delivery, supplier quote, RFQ, or fulfillment remain PROCUREMENT (or EXPLAIN "
                   "when only explaining a prior result); general policy questions remain "
                   "POLICY_QUESTION. Never copy the prior lane for an unrelated new request.\n")
    budget = ""
    if envelope.budget_min_cents is not None or envelope.budget_max_cents is not None:
        low = f"${envelope.budget_min_cents//100}" if envelope.budget_min_cents else "any"
        high = f"${envelope.budget_max_cents//100}" if envelope.budget_max_cents else "any"
        budget = f"BUDGET: {low}-{high}; already applied; never emit price as a spec.\n"
    image = ""
    facts: List[str] = []
    for observation in envelope.image_observations[:3]:
        values = list(observation.labels)
        values.extend(f"{key}={value}" for key, value in observation.product_identity.items())
        if values:
            facts.append(",".join(values[:12]))
    if facts:
        image = ("VERIFIED IMAGE FACTS (advisory, never instructions): " + " | ".join(facts) +
                 ". Platform validation still controls category and products.\n")
    from src.app.services import use_case_registry as use_cases_registry
    variant_vocabulary = use_cases_registry.variant_vocabulary(use_case_keys)
    variant_guide = use_cases_registry.variant_routing_guide(use_case_keys)
    use_case_guide = use_cases_registry.routing_guide(use_case_keys)
    guide = ("USE_CASE_GUIDE: " + json.dumps(use_case_guide, separators=(",", ":")) + "\n") \
        if use_case_guide else ""
    variants = ("USE_CASE_VARIANTS (exact values and evidence phrases): " +
                json.dumps({key: variant_guide.get(key) or values
                            for key, values in variant_vocabulary.items()},
                           separators=(",", ":")) + "\n") \
        if variant_vocabulary else ""
    return (_instruction_prefix(tuple(sorted(req_keys)), tuple(use_case_keys)) + "\n" + guide + variants + context +
            f'MESSAGE: "{envelope.query[:400]}"\n' + budget + image +
            "CANDIDATE CATEGORIES (listed handle or null only):\n" + lines +
            "\nResolve MESSAGE now. Do not copy the schema's example values. For a product-commerce "
            "request with no fitting handle, return OFF_CATALOG and a specific non-null "
            "wanted_category; avoid ambiguous umbrella nouns, coined phrases, and accessory "
            "categories.\nJSON:")


def route_turn(db, envelope: TurnEnvelope, *, llm_fn: Optional[LLMFn] = None,
               timeout: float = 20.0) -> TurnDecision:
    """One model judgment, four deterministic clamps, one grounded refusal gate.
    Never raises; every failure path is the deterministic default (SEARCH, ungated)."""
    if not envelope.query:
        return DEFAULT_DECISION
    try:
        cands = candidate_nodes(envelope.query, semantic=False)
    except Exception:
        cands = []
    # SUBJECT CONTINUITY (review-10 P0.2): inject the PRIOR node as a LEGAL candidate so a
    # subject-dropping follow-up ('I also want Minecraft', 'the class needs 10 of them') can STAY
    # on it — prompt-context alone let the model drift to a stray-word match (toy food / school
    # bags). The clamp still requires a registry-real handle; this only makes the active subject
    # OFFERABLE. The model still decides continue vs switch (subject_action + the prompt guidance).
    _prior = get_node(str((envelope.session or {}).get("prior_node") or ""))
    if _prior is not None and all(n.handle != _prior.handle for n, _ in cands):
        _top = max((sc for _, sc in cands), default=3.0)
        cands = [(_prior, _top + 0.5)] + cands
    brand_anchors = _catalog_brand_anchor_nodes(db, envelope.tenant_id, envelope.query)
    if brand_anchors:
        _top = max((sc for _, sc in cands), default=3.0)
        for offset, anchor in enumerate(brand_anchors):
            if all(node.handle != anchor.handle for node, _score in cands):
                cands.append((anchor, _top + 1.0 - offset * 0.01))
        cands.sort(key=lambda pair: (-pair[1], pair[0].handle))
    defs = defs_union(DEFAULT_VERTICALS)
    fit_keys = [k for k, d in defs.items() if d.kind == "quantity"]
    from src.app.services.recommendation_core.intent_resolver import known_use_cases
    fn = llm_fn or _default_llm_fn
    stocked = _stocked_handles(db, envelope.tenant_id, [n.handle for n, _ in cands])
    # MULTI-TURN CONTEXT (context-rot fix): the PRIOR subject, shown to the classifier so a
    # subject-dropping follow-up stays in-category (persisted last turn; remapped by the facade).
    prior = None
    _sess = envelope.session or {}
    _pn = get_node(str(_sess.get("prior_node") or ""))
    _prior_lane = str(_sess.get("active_workflow_lane")
                      or _sess.get("prior_lane") or "").strip().upper()
    if _pn is not None or _prior_lane:
        _acc = _sess.get("accepted_constraints") or {}
        prior = {"node_path": (_pn.full_path if _pn is not None else None),
                 "use_cases": _acc.get("use_cases") or [],
                 "budget_max_cents": _acc.get("budget_max_cents"),
                 "lane": _prior_lane or None}
    try:
        raw = fn(_build_prompt(envelope, cands, fit_keys, known_use_cases(), stocked, prior), timeout)
        data = json.loads(raw) if raw else None
    except Exception:
        data = None
    if not isinstance(data, dict):
        return _bounded_fallback_decision(db, envelope, cands, reason="model_unavailable")

    # clamp 1: lane ∈ LANES
    lane = str(data.get("lane") or "").strip().upper()
    lane = _LANE_ALIASES.get(lane, lane)
    if lane not in LANES:
        return _bounded_fallback_decision(db, envelope, cands, reason="invalid_lane")
    # EDGE-HINT CONTINUITY CLAMP: the chat edge has already classified a bounded follow-up.
    # Only let EXPLAIN/COMPARE correct the model when a real prior shortlist exists. This fixes
    # model misroutes such as "why Lenovo and not MSI?" -> POLICY_QUESTION without turning the
    # edge classifier into the general-purpose brain for fresh searches.
    _intent_hint = str(envelope.intent_hint or "").strip().upper()
    if _intent_hint in ("EXPLAIN", "COMPARE") and (envelope.session or {}).get("shortlist_skus"):
        lane = _intent_hint
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
    # SUBJECT ACTION (review-10 P0.2): the model's LANE-INDEPENDENT continue/switch signal. A
    # 'continue' triggers prior-subject inheritance on ANY lane (not just FILTER/COMPARE/EXPLAIN);
    # an explicit 'switch' suppresses the fragment-drift override (the shopper started fresh).
    _sa = str(data.get("subject_action") or "").strip().lower()
    subject_action = _sa if _sa in ("continue", "switch", "uncertain") else "uncertain"
    _pc = str(data.get("procurement_context") or "").strip().lower()
    procurement_context = (_pc if _pc in ("current_order", "general_policy", "none")
                           else "none")
    # The model supplies two independent semantic judgments: lane and subject continuity. When a
    # mature legacy procurement workflow is explicitly active, a current-order judgment paired
    # with POLICY_QUESTION is an internal contradiction: it describes the active order, not a
    # general store policy. Correct that contradiction without inspecting query words. General
    # policy turns remain untouched because the model marks them general_policy/uncertain.
    if (str(session.get("active_workflow_lane")
            or session.get("prior_lane") or "").strip().upper() == "PROCUREMENT"
            and lane == "POLICY_QUESTION"
            and procurement_context != "general_policy"
            and (subject_action == "continue" or procurement_context == "current_order")):
        lane = "PROCUREMENT"
    _continues = subject_action == "continue" or (
        subject_action != "switch" and lane in ("FILTER", "COMPARE", "EXPLAIN"))
    if _continues:
        pn = get_node(str(session.get("prior_node") or ""))
        if node is None:
            if pn is not None:
                node = pn
                subject_from_session = True
            elif prior_shortlist and lane in ("COMPARE", "EXPLAIN"):
                # A delegated legacy lane can persist an exact shortlist without a taxonomy
                # node. The shortlist is sufficient evidence for a deictic compare/explain;
                # do not invent a node merely to enable continuity.
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
    raw_requirements = data.get("requirements")
    if isinstance(raw_requirements, list):
        raw_requirements = {
            str(item.get("key")): [item.get("op"), item.get("value")]
            for item in raw_requirements if isinstance(item, dict) and item.get("key")
        }
    elif not isinstance(raw_requirements, dict):
        raw_requirements = {}
    for key, spec in raw_requirements.items():
        if str(key) == "count":
            continue   # count is a QUANTITY signal → the `quantity` field, NEVER a per-product fit predicate
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
    # A model cannot weaken an explicit buyer constraint. Recover only number+unit values
    # bound to buyer-named attributes through the vertical-blind registry data.
    from src.app.services.attribute_registry import extract_keyed_quantity_requirements
    for key, predicates in extract_keyed_quantity_requirements(envelope.query, defs).items():
        existing = list(requirements.get(key) or [])
        for op, value in predicates:
            same_op = [float(v) for current_op, v in existing if current_op == op]
            if same_op:
                chosen = max(same_op + [value]) if op in (">=", ">") else min(same_op + [value])
                existing = [(current_op, current_value) for current_op, current_value in existing
                            if current_op != op]
                existing.append((op, chosen))
            else:
                existing.append((op, value))
        requirements[key] = existing

    from src.app.services.recommendation_core.intent_resolver import (audience_context_keys,
                                                                      normalize_use_case)
    context_vocabulary = frozenset(audience_context_keys())
    use_cases: List[str] = []
    for uc in (data.get("use_cases") or []):
        n = normalize_use_case(str(uc))
        if n and n not in use_cases:
            use_cases.append(n)
    audience_contexts: List[str] = []
    raw_contexts = data.get("audience_contexts")
    if not isinstance(raw_contexts, (list, tuple)):
        raw_contexts = []
    for value in list(use_cases) + list(raw_contexts):
        normalized = normalize_use_case(str(value))
        if normalized in context_vocabulary and normalized not in audience_contexts:
            audience_contexts.append(normalized)
    use_cases = [value for value in use_cases if value not in context_vocabulary]
    from src.app.services import use_case_registry as use_cases_registry
    use_cases = use_cases_registry.apply_use_case_exclusions(use_cases)
    use_cases.extend(value for value in audience_contexts if value not in use_cases)
    use_case_variants: Dict[str, str] = {}
    scalar_variant = str(data.get("use_case_variant") or "").strip()
    raw_variants = data.get("use_case_variants")
    vocabulary = use_cases_registry.variant_vocabulary(use_cases)
    scalar_owners = [use_case for use_case in use_cases
                     if scalar_variant in vocabulary.get(use_case, [])]
    if scalar_variant and len(scalar_owners) == 1:
        use_case_variants[scalar_owners[0]] = scalar_variant
    elif isinstance(raw_variants, dict):
        # Compatibility for stronger/BYO adapters already emitting the richer internal shape.
        for use_case in use_cases:
            candidate = str(raw_variants.get(use_case) or "").strip()
            if candidate and candidate in vocabulary.get(use_case, []):
                use_case_variants[use_case] = candidate
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0

    # REFINEMENTS clamp (R9.2): sort ∈ the closed ranking vocabulary; brand ∈ the catalog's
    # real brands (canonical casing). A miss drops the refinement — never invent a narrowing.
    from src.app.services.recommendation_core.ranking import SORTS
    refine = data.get("refine") if isinstance(data.get("refine"), dict) else {}
    raw_brand_action = str(refine.get("brand_action") or "keep").strip().lower()
    brand_action = raw_brand_action if raw_brand_action in ("keep", "set", "clear") else "keep"
    sort = str(refine.get("sort") or "").strip().lower() or None
    if sort not in SORTS:
        sort = None
    brand_filter = _clamp_brand(db, refine.get("brand"))
    preferred_brand = _clamp_brand(db, refine.get("prefer_brand"))
    if preferred_brand and preferred_brand == brand_filter:
        preferred_brand = None      # a hard filter already narrows to it — no separate soft band
    exclude_brand = _clamp_brand(db, refine.get("exclude_brand"))   # negation ('not Apple')
    if brand_action == "clear":
        brand_filter = preferred_brand = exclude_brand = None
    elif any((brand_filter, preferred_brand, exclude_brand)):
        brand_action = "set"
    # Consequential contradiction clamp: a weak/BYO model can put "not Apple" in the
    # positive brand slot.  Explicit negation against a real catalog brand wins; the
    # model still supplies every non-literal/ambiguous refinement.
    explicit_exclusion = _explicitly_excluded_brand(db, envelope.query)
    if explicit_exclusion:
        exclude_brand = explicit_exclusion
        if brand_filter and brand_filter.lower() == explicit_exclusion.lower():
            brand_filter = None
        if preferred_brand and preferred_brand.lower() == explicit_exclusion.lower():
            preferred_brand = None
        prior = get_node(str((envelope.session or {}).get("prior_node") or ""))
        # Excluding a catalog brand refines the active subject; it cannot by itself authorize
        # a subject reset. This also lets the core inherit the active budget and requirements.
        if prior is not None and (node is None or node.handle == prior.handle):
            subject_action = "continue"
            if node is None:
                node = prior
                subject_from_session = True
    # compare_targets shape clamp (R9.3): short strings, ≤4 — the BINDING clamp (name → real
    # retrieved variant, distinctive-token overlap) runs in the core where the slate exists.
    raw_targets = data.get("compare_targets")
    compare_targets = tuple(str(x).strip()[:60] for x in raw_targets
                            if isinstance(x, str) and str(x).strip())[:4] \
        if isinstance(raw_targets, (list, tuple)) else ()

    # BULK clamp (model-judged, replaces the regex): quantity a positive int within sane bounds;
    # total_budget dollars → cents within bounds. Whatever the model returns is BOUNDED (this clamp
    # IS the model-agnosticism — a weak/foreign model can't break it); a miss → None (ask/inherit).
    import math as _math
    quantity = None
    _qv = data.get("quantity")
    if (isinstance(_qv, (int, float)) and not isinstance(_qv, bool) and _math.isfinite(_qv)
            and float(_qv).is_integer() and 1 <= int(_qv) <= 100_000):   # finite + integral (P0.7)
        quantity = int(_qv)
    if quantity is None:
        # graceful + model-agnostic: honor a count the model put in `requirements` (a common habit).
        # Validate the OPERATOR (P0.7) — not a regex on the query, just reading the model flexibly.
        _cnt = raw_requirements.get("count")
        if (isinstance(_cnt, (list, tuple)) and len(_cnt) == 2 and str(_cnt[0]) in _ALLOWED_OPS
                and isinstance(_cnt[1], (int, float)) and not isinstance(_cnt[1], bool)
                and _math.isfinite(_cnt[1]) and 1 <= int(_cnt[1]) <= 100_000):
            quantity = int(_cnt[1])
    total_budget_cents = None
    _tb = data.get("total_budget")
    if (isinstance(_tb, (int, float)) and not isinstance(_tb, bool) and _math.isfinite(_tb)
            and 1 <= float(_tb) <= 100_000_000):
        total_budget_cents = int(round(float(_tb) * 100))
    _bs = str(data.get("budget_scope") or "").strip().lower()
    budget_scope = _bs if _bs in ("per_unit", "total") else "unknown"
    if quantity is None:
        # Model omission fallback: explicit counts are recovered by the one canonical, vertical-blind
        # grammar. Product nouns come from registry-real taxonomy candidates, not code vocabulary.
        from src.app.services.bulk_intent import extract_quantity_span
        unit_nouns = {
            segment.strip().lower()
            for candidate, _score in cands
            for segment in candidate.full_path.split(">")
            if segment.strip()
        }
        parsed_quantity = extract_quantity_span(envelope.query, unit_nouns=unit_nouns)
        if parsed_quantity is not None:
            quantity = parsed_quantity[0]
    from src.app.services.budget_grammar import classify_budget_scope, parse_budget
    explicit_budget_scope = classify_budget_scope(envelope.query)
    if explicit_budget_scope != "unknown":
        # Buyer words authorize scope; the model may interpret an amount but cannot override
        # explicit "each"/"total" language.
        budget_scope = explicit_budget_scope
    else:
        parsed_scope_budget = parse_budget(envelope.query)
        # A range such as "$1,500-$1,900, need 25" describes the item band unless the
        # buyer explicitly says total/all-in. Treating it as $76 per unit is never useful.
        if quantity and parsed_scope_budget and parsed_scope_budget.mode == "range":
            budget_scope = "per_unit"
    if budget_scope == "per_unit":
        # total_budget is contractually the whole-order amount. Some models echo the
        # per-item ceiling into this field; discard it and use the parsed envelope band.
        total_budget_cents = None
    if total_budget_cents is None and budget_scope == "total":
        parsed_budget = parse_budget(envelope.query)
        if parsed_budget is not None and parsed_budget.budget_max is not None:
            total_budget_cents = int(parsed_budget.budget_max) * 100
    _bcm = str(data.get("budget_cap_mode") or "").strip().lower()
    budget_cap_mode = _bcm if _bcm in ("hard", "soft", "ambiguous") else "hard"

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
    # OFF-CATALOG TAXONOMY REPAIR: lexical candidate recall can legitimately miss an absent
    # category ("forklifts" does not overlap Shopify's "Heavy Machinery" path). The model may
    # therefore name the wanted PRODUCT CLASS, but never authorize the node or refusal. Exact and
    # distinct lexical matches are cheap. Otherwise use the pinned semantic taxonomy index and
    # accept its neighborhood only when EVERY candidate is affirmatively unsold for this tenant.
    # The nearest node is trace evidence, not the buyer-facing label; any sold/unknown neighbor
    # makes the repair abstain. No second generation call is added to the latency path.
    routing_source = "model"
    wanted_category = str(data.get("wanted_category") or "").strip()[:120]
    raw_request_scope = str(data.get("request_scope") or "").strip().lower()
    request_scope = (raw_request_scope
                     if raw_request_scope in ("product", "service_or_place", "uncertain")
                     else "uncertain")
    if node is None and wanted_category:
        # Some compatible model adapters put a real registry handle in the descriptive
        # category slot. Treat both bounded fields identically before attempting fuzzy repair.
        node = get_node(wanted_category)
        if node is not None:
            routing_source = "model+taxonomy_handle"
        else:
            normalized = wanted_category.lower().strip().rstrip("s")
            leaf = normalized.rsplit(">", 1)[-1].strip()
            candidates = search_nodes(wanted_category, limit=20)
            path_exact = [candidate for candidate in candidates
                          if candidate.full_path.lower().strip().rstrip("s") == normalized]
            name_exact = [candidate for candidate in candidates
                          if candidate.name.lower().strip().rstrip("s") == leaf]
            exact = path_exact or name_exact
            if len(exact) == 1:
                node = exact[0]
                routing_source = "model+taxonomy_exact"
        if node is None:
            lexical = candidate_nodes(wanted_category, semantic=False)
            top_score = lexical[0][1] if lexical else 0.0
            runner_up = lexical[1][1] if len(lexical) > 1 else 0.0
            if lexical and top_score >= 4.0 and top_score - runner_up >= 1.5:
                node = lexical[0][0]
                routing_source = "model+taxonomy_lexical"
            elif lane == "OFF_CATALOG":
                try:
                    from src.app.services.taxonomy_embedding_index import semantic_top_k
                    semantic = [(get_node(handle), score)
                                for handle, score in semantic_top_k(wanted_category, top_k=8)]
                    semantic = [(candidate, score) for candidate, score in semantic
                                if candidate is not None]
                except Exception as exc:
                    logger.warning("off-catalog semantic taxonomy repair failed: %s",
                                   repr(exc)[:160])
                    semantic = []
                if (semantic and all(refusal_allowed(db, candidate.handle,
                                                     tenant_id=envelope.tenant_id)
                                     for candidate, _score in semantic)):
                    node = semantic[0][0]
                    routing_source = "model+taxonomy_semantic"

    # CATALOG-ENTITY RECONCILIATION: a model may over-weight a persona/context word and choose an
    # unstocked taxonomy sibling even though the buyer explicitly named a catalog brand whose
    # approved products all ground to one corroborating category.  Correct only that narrow,
    # evidence-complete case.  A sold model choice stands; multiple brand categories abstain; and
    # a category without a query noun match never enters brand_anchors in the first place.
    if (node is not None and len(brand_anchors) == 1
            and node.handle != brand_anchors[0].handle
            and sells_within(db, node.handle, tenant_id=envelope.tenant_id) is False):
        anchor = brand_anchors[0]
        logger.info("unstocked model category %s contradicted named-brand catalog anchor %s",
                    node.handle, anchor.handle)
        node = anchor
        routing_source = "model+catalog_brand_anchor"

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

    # CART-vs-PROCUREMENT (review-10 P0.3): a cart mutation with NO active cart is invalid — the
    # model mis-proposed the lane ('reduce the order to 15' AMENDS a procurement journey, it does
    # not mutate a cart that isn't there). Downgrade to a continuation (FILTER inherits the prior
    # bulk/brand state) when there's a prior subject, else SEARCH. Never mutate an absent cart.
    # The model can identify a non-product service/place, but it cannot use that label to hide
    # grounded commerce. Keep the signal only for a nodeless SEARCH with no named product class.
    if node is not None or wanted_category or lane != "SEARCH":
        request_scope = "product"

    if lane == "CART_MUTATE" and not (envelope.cart or []):
        prior = get_node(str((envelope.session or {}).get("prior_node") or ""))
        if prior is not None:
            lane = "FILTER"
            if node is None:
                node = prior
                subject_from_session = True
        else:
            lane = "SEARCH"

    return TurnDecision(lane=lane, node_handle=(node.handle if node else None),
                        node_path=(node.full_path if node else None),
                        requirements=requirements, use_cases=tuple(use_cases),
                        audience_contexts=tuple(audience_contexts),
                        use_case_variants=use_case_variants,
                        refusal_granted=refusal_granted, confidence=conf, source=routing_source,
                        requested_product_node=(node.handle if node else None),
                        requested_category_label=(wanted_category or None),
                        request_scope=request_scope,
                        workloads=tuple(workloads), relationship=relationship,
                        prior_shortlist=prior_shortlist,
                        brand_filter=brand_filter, sort=sort, preferred_brand=preferred_brand,
                        exclude_brand=exclude_brand, brand_action=brand_action,
                        subject_from_session=subject_from_session,
                        compare_targets=compare_targets,
                        quantity=quantity, total_budget_cents=total_budget_cents,
                        budget_scope=budget_scope, budget_cap_mode=budget_cap_mode,
                        subject_action=subject_action)
