"""LLM intent-planner FALLBACK (agnostic core, governed).

The deterministic decomposer handles the common cases; for the RESIDUAL novel phrasings it can't
parse (low-confidence: no category + no use-cases on a non-trivial query) this asks an LLM for a
STRUCTURED PLAN — never an action.

Governance: the LLM output is validated against a field whitelist AND the active store's vocabulary
(category ∈ profile primary_types, use_cases ∈ profile use_cases) — anything else is dropped. The
merge only FILLS GAPS the rules missed (never overrides a confident rule extraction). The plan is
data, not an action: the deterministic agents still execute and the policy gate still decides. The
LLM call is bounded (timeout passed to llm_fn; the async caller should additionally wrap it in
to_thread+wait_for for a hard bound). Flag-gated default-off (LLM_PLANNER_ENABLED).

Agnostic: the prompt is seeded from the ACTIVE StoreProfile, so core carries no vertical vocabulary.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

_ALLOWED_INTENTS = {
    "product_search", "comparison", "knowledge", "support", "availability", "recommendation_multi",
}


def llm_planner_enabled() -> bool:
    return str(os.getenv("LLM_PLANNER_ENABLED", "0")).strip().lower() in ("1", "true", "yes")


def is_low_confidence(plan: Any) -> bool:
    """True when the deterministic plan extracted little from a NON-TRIVIAL query — the residual the
    rules miss. Cheap + deterministic; short queries are left to the (correct) rules.

    Primary signal: the decomposer's own ``decomposition_confidence`` (0..1, a count of the structured
    fields the rules pulled out) — computed since WS2 but previously UNCONSUMED here (2026-07-07 audit):
    the old no-category-AND-no-use-case rule missed the "category found but everything else vague"
    residual. Threshold via LLM_PLANNER_CONF_THRESHOLD (default 0.45); the legacy rule stays as the
    fallback for plans without the attribute."""
    q = str(getattr(plan, "query", "") or "")
    if len(q.split()) < 4:
        return False
    try:
        conf = float(getattr(plan, "decomposition_confidence"))
        thr = float(os.getenv("LLM_PLANNER_CONF_THRESHOLD", "0.45") or 0.45)
        if conf < thr:
            return True
    except (TypeError, ValueError, AttributeError):
        pass
    cat = getattr(plan, "category", None)
    ucs = getattr(plan, "use_cases", None) or []
    return (not cat) and (not ucs)


def _profile_vocab(profile_id: Optional[str] = None) -> Tuple[List[str], List[str]]:
    from src.app.platform.store_profile import profile_slot
    types = profile_slot("primary_types", profile_id=profile_id, default=None)
    ucs = profile_slot("use_cases", profile_id=profile_id, default=None)
    type_list = [str(t).strip() for t in types if str(t).strip()] if isinstance(types, list) else []
    if isinstance(ucs, dict):
        uc_list = [str(k).strip() for k in ucs.keys() if str(k).strip()]
    elif isinstance(ucs, list):
        uc_list = [str(u).strip() for u in ucs if str(u).strip()]
    else:
        uc_list = []
    return type_list[:30], uc_list[:40]


def _build_prompt(query: str, type_list: List[str], uc_list: List[str],
                  image_identity: Optional[Dict[str, Any]] = None) -> str:
    # When the buyer attached a photo, the CV-identified product IS part of the intent: "something
    # like this but cheaper" is undecomposable from text alone — the identity line resolves "this".
    img_line = ""
    if isinstance(image_identity, dict) and any(image_identity.get(k) for k in ("brand", "model", "category")):
        img_line = (
            "The buyer ATTACHED A PHOTO identified as: "
            f"brand={image_identity.get('brand') or 'unknown'}, model={image_identity.get('model') or 'unknown'}, "
            f"category={image_identity.get('category') or 'unknown'}. Words like 'this'/'it'/'like this' refer to "
            "that product.\n"
        )
    return (
        "Extract a structured shopping plan as STRICT JSON (no prose). Use ONLY this store's "
        f"vocabulary.\nproduct types: {type_list}\nuse_cases: {uc_list}\n"
        + img_line +
        "Keys: intent (one of product_search|comparison|knowledge|availability), category (one product "
        "type or null), use_cases (subset list), budget_min (int|null), budget_max (int|null), "
        "quantity (int|null).\n"
        f"Query: {query!r}\nJSON:"
    )


def _default_llm_fn(prompt: str, timeout: float) -> str:
    """Best-effort platform LLM call (tier-1/fast). Returns a value (never a silent pass)."""
    try:
        from src.app.services.llm_router import generate_text
        res = generate_text(prompt, tier=1)
        if isinstance(res, dict):
            return str(res.get("text") or res.get("content") or res.get("response") or res.get("message") or "")
        return str(res or "")
    except Exception:
        return ""


def _validate_plan(raw: Any, type_list: List[str], uc_list: List[str]) -> Optional[Dict[str, Any]]:
    """Whitelist + vocabulary-clamp the LLM output. Returns a clean dict or None."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else None)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return None
    out: Dict[str, Any] = {}
    intent = str(data.get("intent") or "").strip().lower()
    if intent in _ALLOWED_INTENTS:
        out["intent"] = intent
    types_lc = {t.lower() for t in type_list}
    cat = data.get("category")
    if isinstance(cat, str) and cat.strip() and (not types_lc or cat.strip().lower() in types_lc):
        out["category"] = cat.strip().lower()
    allowed_uc = {u.lower() for u in uc_list}
    ucs_in = data.get("use_cases") or []
    if isinstance(ucs_in, list):
        ucs = [
            str(u).strip().lower() for u in ucs_in
            if str(u).strip() and (not allowed_uc or str(u).strip().lower() in allowed_uc)
        ]
        if ucs:
            out["use_cases"] = ucs
    for k in ("budget_min", "budget_max", "quantity"):
        v = data.get(k)
        if isinstance(v, (int, float)) and 0 < v <= 1_000_000:
            # budgets share the grammar's >=50 sanity floor (a "$3 budget" is an extraction error)
            if k.startswith("budget") and v < 50:
                continue
            out[k] = int(v)
    # a min above max is an LLM slip, not a signal — swap rather than ship an impossible band
    if out.get("budget_min") is not None and out.get("budget_max") is not None and out["budget_min"] > out["budget_max"]:
        out["budget_min"], out["budget_max"] = out["budget_max"], out["budget_min"]
    return out or None


def seed_plan_from_image(plan: Any, image_identity: Optional[Dict[str, Any]],
                         profile_id: Optional[str] = None) -> List[str]:
    """Gap-fill the deterministic plan from the CV-identified product BEFORE any LLM runs — image
    facts become decomposition INPUT, not a post-hoc constraint patch (2026-07-07 lever A5/P6).
    Same contract as merge_llm_plan: fills only gaps, clamps category to the profile vocabulary,
    mutates plan, returns the filled field names for tracing. Never raises."""
    if not isinstance(image_identity, dict):
        return []
    filled: List[str] = []
    try:
        if hasattr(plan, "has_image") and not getattr(plan, "has_image", False):
            plan.has_image = True
        cat = str(image_identity.get("category") or "").strip().lower()
        if cat and not getattr(plan, "category", None):
            type_list, _ = _profile_vocab(profile_id)
            types_lc = {t.lower() for t in type_list}
            if not types_lc or cat in types_lc or cat.rstrip("s") in types_lc:
                plan.category = cat.rstrip("s") if (types_lc and cat not in types_lc) else cat
                filled.append("category")
    except Exception:
        return filled
    return filled


def plan_with_llm(
    query: str,
    *,
    profile_id: Optional[str] = None,
    llm_fn: Optional[Callable[[str, float], str]] = None,
    timeout_sec: Optional[float] = None,
    image_identity: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Ask the LLM for a validated structured plan. Returns a clean dict (whitelisted + vocab-clamped)
    or None. Never raises. llm_fn(prompt, timeout) -> JSON string (injected for tests)."""
    q = str(query or "").strip()
    if not q:
        return None
    type_list, uc_list = _profile_vocab(profile_id)
    prompt = _build_prompt(q, type_list, uc_list, image_identity=image_identity)
    budget = float(timeout_sec if timeout_sec is not None else os.getenv("LLM_PLANNER_TIMEOUT_SEC", "6.0") or 6.0)
    fn = llm_fn or _default_llm_fn
    try:
        raw = fn(prompt, budget)
    except Exception:
        return None
    return _validate_plan(raw, type_list, uc_list)


def merge_llm_plan(plan: Any, llm_dict: Optional[Dict[str, Any]]) -> List[str]:
    """Merge validated LLM fields INTO the plan, only filling gaps the rules missed (never overriding
    a confident rule extraction). Mutates plan; returns the list of fields it filled (for tracing)."""
    if not isinstance(llm_dict, dict):
        return []
    filled: List[str] = []
    if not getattr(plan, "category", None) and llm_dict.get("category"):
        plan.category = llm_dict["category"]; filled.append("category")
    if not (getattr(plan, "use_cases", None) or []) and llm_dict.get("use_cases"):
        plan.use_cases = list(llm_dict["use_cases"]); filled.append("use_cases")
    if getattr(plan, "budget_max", None) is None and llm_dict.get("budget_max"):
        plan.budget_max = llm_dict["budget_max"]; filled.append("budget_max")
    if getattr(plan, "budget_min", None) is None and llm_dict.get("budget_min"):
        plan.budget_min = llm_dict["budget_min"]; filled.append("budget_min")
    if getattr(plan, "quantity", None) is None and llm_dict.get("quantity"):
        plan.quantity = llm_dict["quantity"]; filled.append("quantity")
    # intent: only upgrade from the default product_search to a specific LLM intent
    if llm_dict.get("intent") and getattr(plan, "intent", None) in (None, "product_search"):
        if plan.intent != llm_dict["intent"]:
            plan.intent = llm_dict["intent"]; filled.append("intent")
    return filled
