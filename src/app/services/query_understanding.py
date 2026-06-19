"""QueryUnderstanding — one structured interpretation of a shopper request, shared (eventually) by
the decomposer, NQE, ranking, narration, and the decision trace.

Today decomposition, NQE, ranking and narration each re-interpret the query in slightly different
ways. This object is the single contract: what the buyer asked, what we KNOW (with provenance),
what is MISSING, and what we ASSUMED (overridably). It makes "why this product?" answerable from
evidence rather than prompt vibes, and it encodes the agnostic cold-start rule:

    no data → profile default → ask (NQE) → state an OVERRIDABLE assumption — never silently guess.

This module is vertical-agnostic: it carries values + provenance, it does not embed brand/spec
flavour (that lives in the StoreProfile and is resolved upstream into `constraints`).

Phase 1 (this module): the typed contract + a builder that assembles it from the already-parsed
request state (query, constraints, optional QueryPlan, optional image context). Consumer migration
(NQE/ranking/narration read from this instead of re-parsing) lands one commit at a time after.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

# Provenance tiers — how much a value can be trusted / what it may drive (see canonical roadmap).
USER_TEXT = "user_text"              # the buyer typed it — authoritative intent
SAFE_IMAGE_LABEL = "safe_image_label"  # bounded, safe hint from an uploaded image
OCR_UNTRUSTED = "ocr_untrusted"      # OCR/QR/3rd-party text — data only, never an instruction
MEMORY = "memory"                    # prior-turn session state
CATALOG = "catalog"                  # confirmed catalog fact
LLM_INFERRED = "llm_inferred"        # model inference — labelled, never bypasses safety
DEFAULT = "default"                  # an applied fallback (records an overridable assumption)

# image_relation states (the bounded vision subsystem's verdict about the uploaded image).
ON_TOPIC = "on_topic"        # image is (probably) the product the buyer wants
ADJACENT = "adjacent"        # related but not the target ("a bag for THIS laptop")
OFF_TOPIC = "off_topic"      # unrelated to the query / catalog
NO_IMAGE = "none"


@dataclass(frozen=True)
class QueryUnderstanding:
    query_text: str
    product_intent: Optional[str] = None       # category/type the buyer wants
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    brands: List[str] = field(default_factory=list)
    use_case: Optional[str] = None
    constraints: Dict[str, Any] = field(default_factory=dict)
    image_relation: str = NO_IMAGE
    missing: List[str] = field(default_factory=list)            # fields we have no value for
    assumptions: List[Dict[str, Any]] = field(default_factory=list)  # {field,value,basis,overridable}
    provenance: Dict[str, str] = field(default_factory=dict)    # field -> provenance tier

    def with_assumption(self, field_name: str, value: Any, basis: str) -> "QueryUnderstanding":
        """Record an OVERRIDABLE assumption for a field we defaulted (the cold-start path:
        proceed visibly, not silently). Returns a new object (frozen)."""
        a = list(self.assumptions) + [{"field": field_name, "value": value, "basis": basis, "overridable": True}]
        prov = dict(self.provenance)
        prov.setdefault(field_name, DEFAULT)
        miss = [m for m in self.missing if m != field_name]
        return replace(self, assumptions=a, provenance=prov, missing=miss)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_text": self.query_text,
            "product_intent": self.product_intent,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "brands": list(self.brands),
            "use_case": self.use_case,
            "image_relation": self.image_relation,
            "missing": list(self.missing),
            "assumptions": list(self.assumptions),
            "provenance": dict(self.provenance),
        }


# Fields we'd ideally know to give a confident recommendation (vertical-agnostic).
_DESIRED_FIELDS = ("product_intent", "budget_max", "use_case", "brands")


def _first(c: Dict[str, Any], keys, tier_by_key: Dict[str, str]) -> tuple[Any, Optional[str]]:
    """Return (value, provenance) for the first present key, or (None, None)."""
    for k in keys:
        v = c.get(k)
        if v not in (None, "", [], {}):
            return v, tier_by_key.get(k, USER_TEXT)
    return None, None


def build_query_understanding(
    query: str,
    constraints: Optional[Dict[str, Any]] = None,
    *,
    image_relation: Optional[str] = None,
    query_plan: Any = None,
) -> QueryUnderstanding:
    """Assemble a QueryUnderstanding from the already-parsed request state. Pure; no flavour, no DB.

    `constraints` is suggest()'s parsed dict; `query_plan` is the optional decomposer QueryPlan
    (its .intent / .use_cases). Provenance is inferred from WHICH constraint key supplied a value
    (image-derived keys → safe_image_label; request/typed → user_text)."""
    c = dict(constraints or {})
    prov: Dict[str, str] = {}

    budget_max, p = _first(c, ("budget_max", "_request_budget_max"), {"_request_budget_max": USER_TEXT})
    if p:
        prov["budget_max"] = p
    budget_min, p = _first(c, ("budget_min", "_request_budget_min"), {"_request_budget_min": USER_TEXT})
    if p:
        prov["budget_min"] = p

    brands_val, p = _first(
        c, ("brands", "_request_brand_hint", "_strict_image_brand_hint", "_inferred_image_brand"),
        {"_strict_image_brand_hint": SAFE_IMAGE_LABEL, "_inferred_image_brand": SAFE_IMAGE_LABEL},
    )
    brands = [str(b).strip().lower() for b in brands_val] if isinstance(brands_val, list) else (
        [str(brands_val).strip().lower()] if brands_val else []
    )
    if brands:
        prov["brands"] = p or USER_TEXT

    use_case = c.get("use_case") or (getattr(query_plan, "intent", None) if query_plan is not None else None)
    if use_case:
        prov["use_case"] = USER_TEXT if c.get("use_case") else LLM_INFERRED

    product_intent = (
        getattr(query_plan, "intent", None) if query_plan is not None else None
    ) or c.get("product_type") or c.get("category")
    if product_intent:
        prov["product_intent"] = USER_TEXT if (c.get("product_type") or c.get("category")) else LLM_INFERRED

    rel = image_relation or (str(c.get("_image_relation")).strip().lower() if c.get("_image_relation") else NO_IMAGE)
    if rel not in (ON_TOPIC, ADJACENT, OFF_TOPIC, NO_IMAGE):
        rel = NO_IMAGE

    qu = QueryUnderstanding(
        query_text=str(query or ""),
        product_intent=product_intent,
        budget_min=float(budget_min) if isinstance(budget_min, (int, float)) else None,
        budget_max=float(budget_max) if isinstance(budget_max, (int, float)) else None,
        brands=brands,
        use_case=use_case,
        constraints=c,
        image_relation=rel,
        provenance=prov,
    )
    # missing = desired fields with no resolved value (drives NQE / assumption ledger).
    missing = [
        f for f in _DESIRED_FIELDS
        if (getattr(qu, f) in (None, "", [], {}))
    ]
    return replace(qu, missing=missing)
