"""Model-judged turn routing (the brain shift, 2026-07-10) — replace regex DECISIONS with model
JUDGMENT, clamped to a closed vocabulary and grounded on the capability registry.

WHY this exists: turn classification and off-catalog detection are today ~30 brittle substring
patterns (chat._classify_turn_intent, off_catalog_gate regex). Every paraphrase that misses adds
another token — the "screenshot -> add a regex" treadmill. The same negation-of-"over" bug had to
be fixed in FOUR budget-parser copies. The cure is not more patterns; it is one model decision.

THE SAFE PATTERN (same as llm_planner._validate_plan — proven, not novel):
  model proposes a value from a CLOSED vocabulary
    -> deterministic code CLAMPS it to the enum / registry-declared slugs
    -> caller GUARDS the downstream (registry text is emitted, never model free-text for policy)
    -> FALLS BACK to today's deterministic classifier on ANY miss (empty/invalid/timeout).
The model never invents a lane, a non-sold class, a SKU, a price, or an authorization. A wrong
judgment degrades to the deterministic default — never to an unsafe action.

This is a NEW isolated service: it does NOT run inside suggest(); it is consulted (shadow first,
then routing) by the thin classifiers. Its purpose is to DELETE regex surfaces, not add them.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# The closed lane vocabulary — the model must pick exactly one; anything else clamps to None
# (→ caller uses the deterministic default). Mirrors the deterministic outputs + the lanes the
# regex classifiers can't reliably reach (off-catalog, cart mutation, policy question).
LANES = (
    "SEARCH",          # find/recommend products
    "FILTER",          # narrow an existing search by a constraint
    "COMPARE",         # A vs B / which is better / difference
    "EXPLAIN",         # why / justify / is it enough / overkill
    "SUPPORT_CLAIM",   # post-purchase damage/return/warranty CLAIM
    "CART_MUTATE",     # change/swap/remove/qty on the cart
    "PROCUREMENT",     # bulk / sourcing / reorder-consent / RFQ
    "OFF_CATALOG",     # a hardware/product CLASS the store does not sell
    "POLICY_QUESTION", # do you offer X / delivery / financing / returns policy (pre-sales)
)

LLMFn = Callable[[str, float], str]


@dataclass
class TurnDecision:
    lane: str
    requested_category: Optional[str] = None   # model's world-knowledge product category
    requested_variant: Optional[str] = None    # form-factor/variant (server, laptop, gaming, ottoman)
    in_catalog: Optional[bool] = None          # is (category, variant) one the store SELLS
    policy_topic: Optional[str] = None          # a declared does_not_offer slug, or None
    unresolved: List[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "model"

    def as_dict(self) -> Dict[str, Any]:
        return {"lane": self.lane, "requested_category": self.requested_category,
                "requested_variant": self.requested_variant, "in_catalog": self.in_catalog,
                "policy_topic": self.policy_topic, "unresolved": self.unresolved,
                "confidence": round(self.confidence, 3), "source": self.source}


def _default_llm_fn(prompt: str, timeout: float) -> str:
    """Local Ollama, schema-forced JSON — same call shape as llm_planner._default_llm_fn."""
    try:
        import httpx
        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = (os.getenv("SEMANTIC_ROUTER_MODEL") or os.getenv("MULTI_INTENT_LLM_MODEL")
                 or os.getenv("OLLAMA_SMALL_MODEL") or os.getenv("OLLAMA_DEFAULT_MODEL") or "qwen3:14b")
        payload = {"model": model, "prompt": prompt, "stream": False, "format": "json",
                   "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                   "options": {"temperature": 0, "num_predict": 256}}
        if "qwen3" in model.lower():
            payload["think"] = False
        r = httpx.post(f"{url}/api/generate", json=payload, timeout=max(2.0, float(timeout or 5.0)))
        return str((r.json() or {}).get("response", "") or "")
    except Exception:
        return ""


def _build_prompt(query: str, caps: Dict[str, Any]) -> str:
    does_not_offer = [str(s) for s in (caps.get("does_not_offer") or [])]
    sells = [str(s) for s in (caps.get("sells") or [])]
    # CATEGORY x VARIANT taxonomy reasoning (2026-07-10) — AGNOSTIC. The store declares only what
    # it SELLS (categories + the variants/form-factors within them). The model uses its OWN world
    # knowledge to name the requested (category, variant) and judge membership. NO hand-maintained
    # "things we don't sell" list. Key distinction: a GENERIC SPEC (VRAM=a number, "A100-equivalent"
    # = a performance level) describes an in-catalog product; a FORM-FACTOR (server GPU, rack unit)
    # is a distinct product variant. Same mechanism for any vertical: a chair's variants are
    # ottoman/club/office/gaming; a store sells some, not all.
    return (
        "You are a routing classifier for a commerce assistant. Read the shopper's message and "
        "return STRICT JSON classifying it into exactly ONE lane.\n\n"
        f"LANES (choose one): {', '.join(LANES)}\n"
        f"This store SELLS ONLY these product categories/variants: {sells or 'general consumer products'}.\n"
        f"This store DOES NOT offer these services: {does_not_offer}.\n\n"
        "Reason in CATEGORY + VARIANT (form-factor) using your own product knowledge:\n"
        "- Identify the product CATEGORY (e.g. computer, graphics card, chair) and its VARIANT / "
        "form-factor (e.g. laptop vs desktop vs SERVER; office vs gaming vs ottoman chair).\n"
        "- Separate a GENERIC SPEC from a FORM-FACTOR: 'a laptop with A100-equivalent VRAM' is a "
        "laptop (in-catalog form-factor) described by a spec — NOT a request for a server GPU. "
        "'Five rack-mount A100 servers' is the SERVER form-factor — a different product.\n"
        "Rules:\n"
        "- OFF_CATALOG if the wanted (category, variant) is NOT one the store sells — whether a "
        "whole category it lacks (3D printer, forklift, network switch) OR a form-factor variant it "
        "doesn't carry (server-variant GPU when it only sells laptop/desktop computers). Name both.\n"
        "- IN-catalog (SEARCH/EXPLAIN) when the wanted category+variant IS sold, even if the message "
        "cites a high-end spec for comparison.\n"
        "- POLICY_QUESTION: asks whether you offer a SERVICE (payment plans, financing, delivery, returns).\n"
        "- CART_MUTATE: a change to an existing cart (swap/remove/change qty/make it N).\n"
        "- PROCUREMENT: bulk + sourcing/reorder-consent ('50 units but you only have a few, ok to wait?').\n"
        "- SUPPORT_CLAIM: a POST-PURCHASE damage/return/warranty claim about an owned item.\n\n"
        'Return JSON: {"lane": "<one lane>", '
        '"requested_category": "<product category, or null>", '
        '"requested_variant": "<form-factor/variant, e.g. server, laptop, gaming, ottoman, or null>", '
        '"in_catalog": <true if that category+variant is one the store sells, else false>, '
        '"policy_topic": "<declared does_not_offer slug or null>", '
        '"unresolved": ["<facts needed to answer>"], "confidence": <0.0-1.0>}\n\n'
        f'Shopper message: "{str(query or "")[:400]}"\n'
        "JSON:"
    )


def _clamp(raw: Any, caps: Dict[str, Any]) -> Optional[TurnDecision]:
    """Whitelist the model output to the closed vocabulary. None on any miss (→ deterministic)."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else None)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return None
    lane = str(data.get("lane") or "").strip().upper()
    if lane not in LANES:
        return None
    def _clean(v: Any) -> Optional[str]:
        return str(v).strip()[:60] if (v and str(v).strip().lower() not in ("null", "none")) else None
    req_cat = _clean(data.get("requested_category"))
    req_var = _clean(data.get("requested_variant"))
    in_catalog = data.get("in_catalog")
    in_catalog = bool(in_catalog) if isinstance(in_catalog, bool) else None
    # GROUND the refusal on the POSITIVE sells list (authoritative): OFF_CATALOG is only trusted
    # when the model flags in_catalog=False AND names a category+variant that doesn't match a sold
    # (category OR variant) token. A (category, variant) the store DOES sell can never be refused —
    # the sells list is the ground truth, the model's world knowledge is the mapping.
    sells_lc = {str(s).strip().lower() for s in (caps.get("sells") or [])}
    if lane == "OFF_CATALOG":
        blob = f"{req_cat or ''} {req_var or ''}".lower()
        matches_sold = any(s and s in blob for s in sells_lc)
        if in_catalog is True or matches_sold or not req_cat:
            return None  # not a trustworthy refusal → fall back to normal retrieval
    declared_topics = {str(s) for s in (caps.get("does_not_offer") or [])}
    pt = data.get("policy_topic")
    pt = str(pt) if (pt and str(pt) in declared_topics) else None
    unresolved = [str(u) for u in (data.get("unresolved") or []) if isinstance(u, (str, int))][:5]
    try:
        conf = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return TurnDecision(lane=lane, requested_category=req_cat, requested_variant=req_var,
                        in_catalog=in_catalog, policy_topic=pt, unresolved=unresolved,
                        confidence=max(0.0, min(1.0, conf)))


def classify_turn(query: str, *, profile_id: Optional[str] = None,
                  llm_fn: Optional[LLMFn] = None, timeout: float = 5.0) -> Optional[TurnDecision]:
    """Model-judged lane decision grounded on the capability registry, clamped to the closed
    vocabulary. Returns None on any failure so the caller falls back to the deterministic
    classifier — the model can only ever REPLACE a regex guess with a grounded one, never
    introduce an unsafe outcome. Never raises."""
    if not str(query or "").strip():
        return None
    try:
        from src.app.services.capability_registry import get_capabilities
        caps = get_capabilities(profile_id) or {}
    except Exception:
        caps = {}
    fn = llm_fn or _default_llm_fn
    try:
        raw = fn(_build_prompt(query, caps), timeout)
    except Exception:
        return None
    return _clamp(raw, caps)
