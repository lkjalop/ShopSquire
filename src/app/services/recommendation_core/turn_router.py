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
from src.app.services.taxonomy_registry import get_node

logger = logging.getLogger("shopsquire.recommendation_core.turn_router")

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
    requirements: Dict[str, Tuple[str, float]] = field(default_factory=dict)  # key -> (op, thr)
    use_cases: Tuple[str, ...] = ()              # model-classified, clamped to KB keys
    refusal_granted: bool = False                # sells_within()==False confirmed the refusal
    confidence: float = 0.0
    source: str = "model"                        # model | default

    def as_dict(self) -> Dict[str, Any]:
        return {"lane": self.lane, "node_handle": self.node_handle, "node_path": self.node_path,
                "requirements": {k: list(v) for k, v in self.requirements.items()},
                "use_cases": list(self.use_cases), "refusal_granted": self.refusal_granted,
                "confidence": round(self.confidence, 3), "source": self.source}


DEFAULT_DECISION = TurnDecision(source="default")


def _build_prompt(envelope: TurnEnvelope, cands: List, req_keys: List[str],
                  use_case_keys: List[str]) -> str:
    lines = "\n".join(f"  {n.handle} : {n.full_path}" for n, _ in cands) or "  (none)"
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
        '- POLICY_QUESTION for services (payment plans, delivery, returns policy).\n\n'
        'Return JSON: {"lane": "<lane>", "handle": "<candidate handle or null>", '
        '"use_cases": ["<key>", ...], '
        '"requirements": {"<key>": ["<op one of >=,<=,>,<,==>", <number>]}, '
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
    try:
        raw = fn(_build_prompt(envelope, cands, fit_keys, known_use_cases()), timeout)
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
    # clamp 3: requirements — known keys, known ops, numeric, within sanity bounds
    requirements: Dict[str, Tuple[str, float]] = {}
    for key, spec in (data.get("requirements") or {}).items():
        d = defs.get(str(key))
        if d is None or d.kind != "quantity" or not isinstance(spec, (list, tuple)) or len(spec) != 2:
            continue
        op, thr = str(spec[0]), spec[1]
        if op not in _ALLOWED_OPS or not isinstance(thr, (int, float)) or isinstance(thr, bool):
            continue
        if d.bounds and not (d.bounds[0] <= float(thr) <= d.bounds[1]):
            continue
        # BUDGET-BLEED GUARD (belt-and-suspenders to the prompt fix): drop a spec whose value
        # equals the budget dollars — UNLESS the query actually states that number WITH a
        # storage/memory unit (review #3: '1TB laptop under $1000' → storage_gb 1000 is REAL,
        # not the price). Only drop the mis-parse, never a genuine explicit spec.
        budget_dollars = {c // 100 for c in (envelope.budget_min_cents, envelope.budget_max_cents)
                          if c is not None}
        if (float(thr) in budget_dollars and d.key in ("storage_gb", "ram_gb")
                and not _number_has_size_unit(envelope.query, thr)):
            continue
        requirements[d.key] = (op, float(thr))
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
    if node is not None and _WORKLOAD_RE.match(node.handle):
        capability = bool(requirements) or bool(use_cases) or _CAPABILITY_VERB_RE.search(envelope.query)
        if capability:
            node = None
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
                        refusal_granted=refusal_granted, confidence=conf, source="model")
