"""Pure projection and interpretation helpers used by the chat router.

Keeping these deterministic helpers outside the transport router makes their
policy boundaries independently testable and preserves the router size ratchet.
"""
from __future__ import annotations

from typing import Any, Dict, List

from typing import Optional
import re
import logging
logger = logging.getLogger(__name__)


def _extract_confirmed_slots(*, query: str, response: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    from src.app.services.conversation_case_state import classify_case_turn
    literal_case_turn=classify_case_turn(query,current_state={})
    if literal_case_turn.dialogue_act=='amend_destination':
        out['destination']=literal_case_turn.proposed_value
    if literal_case_turn.dialogue_act=='amend_deadline':
        out['deadline']=literal_case_turn.proposed_value
    budget = _extract_budget_bounds(query)
    if budget.get("budget_min") is not None:
        out["budget_min"] = budget.get("budget_min")
    if budget.get("budget_max") is not None:
        out["budget_max"] = budget.get("budget_max")
    # Preserve whole-order budget semantics across the CART_MUTATE short circuit. Without these
    # typed fields, a later quantity change falls back to the budget from the original search.
    parsed_budget = None
    try:
        from src.app.services.budget_grammar import classify_budget_scope, parse_budget

        budget_scope = classify_budget_scope(query)
        parsed_budget = parse_budget(query)
        if budget_scope == "total" and parsed_budget and parsed_budget.budget_max is not None:
            total_budget = int(parsed_budget.budget_max)
            if total_budget > 0:
                out["budget_scope"] = "total"
                out["total_budget_cents"] = total_budget * 100
                out["budget_max"] = total_budget
        elif budget_scope == "per_unit":
            out["budget_scope"] = "per_unit"
    except Exception:
        logger.warning("confirmed-slot budget parsing failed", exc_info=True)
    brands = _extract_brand_mentions(query)
    if brands:
        out["brands"] = brands[:6]

    data = response if isinstance(response, dict) else {}
    applied = data.get("nqe_selection_applied") if isinstance(data.get("nqe_selection_applied"), dict) else {}
    used = data.get("constraints_used") if isinstance(data.get("constraints_used"), dict) else {}
    # LONG-HORIZON qty memory: the bulk unit count survives non-qty turns the same way budget does —
    # turn 1 "need 25 laptops", turn 3 "which has the best battery?" must still know it's a 25-unit
    # conversation (Add buttons + procurement previews read requested_quantity every turn).
    _rq = data.get("requested_quantity")
    if _rq is None:
        from src.app.services.bulk_intent import extract_quantity_span
        literal_quantity = extract_quantity_span(query)
        if literal_quantity is not None:
            _rq = literal_quantity[0]
    if isinstance(_rq, (int, float)) and 1 <= int(_rq) <= 1000:
        out["order_quantity"] = int(_rq)
    decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
    exact_product_sku = str(decision.get("exact_product_sku") or "").strip()
    if exact_product_sku:
        out["exact_product_sku"] = exact_product_sku
    for key in ("budget_min", "budget_max", "use_case", "gpu_preference", "availability", "condition", "buyer_persona", "issue_type"):
        v = applied.get(key)
        if v is None:
            v = used.get(key)
        if v is not None:
            out[key] = v
    for key in ("brands", "specs", "brand_excludes", "use_case_tags"):
        vv = applied.get(key)
        if vv is None:
            vv = used.get(key)
        if isinstance(vv, list) and vv:
            out[key] = vv[:12]
    # The legacy chat extractor sees every catalog brand token as positive.  Reconcile it
    # with the shared core's clamped exclusion before persisting session memory.
    excluded = {str(v).strip().lower() for v in (out.get("brand_excludes") or []) if str(v).strip()}
    if excluded and isinstance(out.get("brands"), list):
        kept = [v for v in out["brands"] if str(v).strip().lower() not in excluded]
        if kept:
            out["brands"] = kept
        else:
            out.pop("brands", None)
    if isinstance(data.get("product_identity"), dict):
        ident = data.get("product_identity") or {}
        if ident.get("constraints"):
            out["image_identity"] = ident.get("constraints")
    if parsed_budget is not None:
        # A new literal budget replaces both bounds, including an absent one.
        # Response-side retrieval constraints must not rewrite buyer facts.
        out.update(budget_min=parsed_budget.budget_min, budget_max=parsed_budget.budget_max,
                   budget_mode=parsed_budget.mode)
        from src.app.services.commercial_terms import stated_currency
        currency=stated_currency(query,money_only=True)
        if currency:
            out['currency']=currency
    return out


def _extract_budget_bounds(query: str) -> Dict[str, int | None]:
    """Project canonical query-budget facts, including intentional abstention."""
    from src.app.services.budget_grammar import parse_budget

    budget = parse_budget(query)
    return {
        "budget_min": budget.budget_min if budget and budget.found else None,
        "budget_max": budget.budget_max if budget and budget.found else None,
    }


def _is_budget_query_text(query: str | None) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    if any(
        tok in q
        for tok in (
            "budget",
            "under",
            "below",
            "up to",
            "between",
            "only have",
            "is that enough",
            "is this enough",
            "for high school",
            "for school",
            "for university",
            "for work",
            "for gaming",
        )
    ):
        return True
    bounds = _extract_budget_bounds(q)
    return bounds.get("budget_min") is not None or bounds.get("budget_max") is not None or bool(
        re.search(r"\$\s*\d{3,5}\b", q)
    )


_DEFICIT_OBS_RE = re.compile(
    r"only\s+have\s+a?\s*few|few\s+in\s+stock|limited\s+stock|not\s+enough\s+(?:in\s+)?stock|"
    r"wait\w*\s+(?:for|on)\s+(?:a\s+)?(?:re-?order|re-?stock|restock|backorder|back-?order|the\s+rest|stock)|"
    r"ok\s+(?:to\s+|with\s+)?wait|back-?order|re-?order",
    re.I,
)
_BULK_QTY_RE = re.compile(r"\b(\d{2,5})\s+[a-z][a-z\s]{0,24}?(?:laptop|desktop|monitor|tablet|unit|machine|device|pc)s?\b", re.I)


def _strip_deficit_observation(q: str) -> str:
    """Remove the shortfall-observation tail from a deficit-reorder query so retrieval sees only
    the bulk need. 'i need 50 dell laptops but you only have a few in stock, am i ok waiting for a
    reorder?' -> 'i need 50 dell laptops'. Conservative: only cuts at an observation connector so
    a plain bulk request is never truncated."""
    cut = re.split(
        r"\b(?:but|and)\s+(?:you|i|we)\s+(?:only\s+have|have\s+only|think|know)\b|"
        r"\bbut\s+(?:you\s+)?(?:only\s+have|have\s+a?\s*few|few\s+in\s+stock|limited\s+stock)\b|"
        r",?\s*(?:am\s+i\s+ok|is\s+it\s+ok|ok\s+(?:to\s+|with\s+)?wait)\b",
        q, maxsplit=1, flags=re.I,
    )[0].strip().rstrip(",")
    return cut if len(cut) >= 6 else q


def _is_deficit_reorder_query(q: str) -> bool:
    """A bulk QUANTITY need + a deficit/reorder OBSERVATION ("i need 50 dell laptops but you only
    have a few in stock, ok waiting for a reorder?"). The buyer is acknowledging a shortfall and
    asking about backorder — NOT requesting a low-stock filter. Without this it hit
    _classify_turn_intent's `"only " in q` -> FILTER -> the "few in stock" filter zeroed retrieval
    (live: 0 products, backorder capability fact never reached the answer). Routing it to SEARCH
    lets the bulk-sourcing path run (products + sourcing preview + the reorder-consent narration)."""
    if not _DEFICIT_OBS_RE.search(q):
        return False
    return bool(_BULK_QTY_RE.search(q)) or bool(re.search(r"\b\d{2,5}\b", q))


def _classify_turn_intent(query: str) -> str:
    q = str(query or "").strip().lower()
    if not q:
        return "SEARCH"
    # Deficit/reorder-consent BEFORE the FILTER branch: a "you only have a few in stock, ok to
    # wait for a reorder?" turn is a bulk-sourcing intent, not a stock filter (2026-07-09).
    if _is_deficit_reorder_query(q):
        return "SEARCH"
    # CLAIM-CHECKED support detection (shared predicate with recommend.py's classifier): only a genuine
    # post-purchase claim routes to the support lane. The old bare keyword list here hijacked pre-sales
    # policy questions ("what is your warranty policy?") into photo-triage with zero products.
    from src.app.services.answer_quality import is_support_claim, policy_faq_answer
    if is_support_claim(q):
        return "SUPPORT_CLAIM"
    if policy_faq_answer(q) is not None:
        return "POLICY_QUESTION"
    if (
        " vs " in q
        or "compare" in q
        or "difference" in q
        or "show both" in q
        or "which is better" in q
    ):
        return "COMPARE"
    if (
        q.startswith("why ")
        or " why " in q
        or "explain" in q
        or "reason" in q
        or "if not why" in q
        or "overkill" in q
        or "should i" in q
    ):
        return "EXPLAIN"
    if (
        "under $" in q
        or "between $" in q
        or "budget" in q
        or "price range" in q
        or "widen" in q
        or "increase" in q
        or "decrease" in q
        or "only " in q
        or " with " in q
        or "without " in q
    ):
        return "FILTER"
    return "SEARCH"


def _is_budget_question(item: Dict[str, Any]) -> bool:
    text = str((item or {}).get("text") or "").lower()
    qid = str((item or {}).get("id") or "").lower()
    return any(
        tok in text or tok in qid
        for tok in ("budget", "price range", "price", "widen_budget", "budget_range", "increase_match_space")
    )


def _budget_range_from_slots(slots: Dict[str, Any] | None, query: str) -> Dict[str, int | None]:
    out = _extract_budget_bounds(query)
    s = slots if isinstance(slots, dict) else {}
    if out.get("budget_min") is None and s.get("budget_min") is not None:
        try:
            out["budget_min"] = int(float(s.get("budget_min")))
        except Exception:
            pass
    if out.get("budget_max") is None and s.get("budget_max") is not None:
        try:
            out["budget_max"] = int(float(s.get("budget_max")))
        except Exception:
            pass
    return out



def terminal_scope_contract(*, scope, case_id, case_revision, applicable=True):
    """Describe binding truth without inventing scope for an early/degraded exit."""
    if not applicable:
        return {"catalog_scope": None, "catalog_scope_status": "not_applicable"}
    bound = bool(
        isinstance(scope, dict) and case_id and case_revision
        and scope.get("case_id") == case_id
        and scope.get("case_revision") == case_revision
    )
    return {
        "catalog_scope": dict(scope) if bound else None,
        "catalog_scope_status": "bound" if bound else "unavailable",
    }

def _compute_widened_budget(bounds: Dict[str, int | None], widen_delta: int) -> Dict[str, int]:
    bmin = bounds.get("budget_min")
    bmax = bounds.get("budget_max")
    delta = max(100, int(widen_delta or 200))
    if bmax is not None and bmin is not None:
        lo = int(bmax)
        hi = int(bmax + delta)
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    if bmax is not None:
        lo = int(bmax)
        hi = int(bmax + delta)
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    if bmin is not None:
        lo = int(bmin + delta)
        hi = int(bmin + (delta * 2))
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    # No prior budget: deterministic bootstrap window.
    return {"budget_min": 800, "budget_max": 1200}


def _brand_hint_from_text(text: str) -> str | None:
    t = str(text or "").lower()
    aliases = [
        ("apple", ("apple", "macbook", "mac")),
        ("lenovo", ("lenovo", "legion", "thinkpad", "yoga")),
        ("dell", ("dell", "xps", "inspiron", "latitude", "alienware")),
        ("hp", ("hp", "pavilion", "omen", "spectre", "envy", "elitebook")),
        ("asus", ("asus", "rog", "zenbook", "vivobook", "tuf")),
        ("msi", ("msi", "katana", "stealth", "raider")),
        ("acer", ("acer", "nitro", "predator", "swift")),
        ("microsoft", ("microsoft", "surface")),
    ]
    for canonical, toks in aliases:
        if any(tok in t for tok in toks):
            return canonical
    return None


def _image_anchor_hint(image_obj: Dict[str, Any], idx: int) -> Dict[str, Any]:
    labels = image_obj.get("labels") if isinstance(image_obj.get("labels"), list) else []
    ocr_text = str(image_obj.get("ocr_text") or "")
    joined = " ".join([str(x) for x in labels[:20]]) + " " + ocr_text
    brand = _brand_hint_from_text(joined)
    low = joined.lower()
    use_case_hint = "general"
    if any(tok in low for tok in ("esports", "gaming", "rtx", "geforce", "fps", "legion", "rog", "tuf")):
        use_case_hint = "gaming"
    elif any(tok in low for tok in ("office", "business", "work", "excel", "powerpoint")):
        use_case_hint = "office"
    elif any(tok in low for tok in ("creator", "premiere", "davinci", "render", "editing")):
        use_case_hint = "content_creator"
    elif any(tok in low for tok in ("student", "school", "college", "university", "study")):
        use_case_hint = "student"
    return {
        "anchor_id": str(image_obj.get("image_hash") or f"img_{idx+1}"),
        "title": f"Image {idx+1}",
        "brand_hint": brand,
        "use_case_hint": use_case_hint,
        "ocr_excerpt": ocr_text[:120] if ocr_text else "",
        "image_hash": str(image_obj.get("image_hash") or ""),
    }

def _persona_rank_weights(use_case_key: str | None, buyer_persona: str | None) -> Dict[str, float]:
    key = str(use_case_key or buyer_persona or "").lower()
    # Keep this deterministic and lightweight: no model call, just profile weights.
    if key in {"gaming", "gamer"}:
        return {"budget_fit": 0.30, "brand_match": 0.10, "performance": 0.50, "portability": 0.10}
    if key in {"ai_ml_workstation", "data_science_student", "engineering_student", "ai", "data_science"}:
        return {"budget_fit": 0.25, "brand_match": 0.10, "performance": 0.55, "portability": 0.10}
    if key in {"office_general", "office", "business", "corporate"}:
        return {"budget_fit": 0.35, "brand_match": 0.10, "performance": 0.20, "portability": 0.35}
    if key in {"content_creator", "content_creation", "creator", "design_student"}:
        return {"budget_fit": 0.25, "brand_match": 0.10, "performance": 0.45, "portability": 0.20}
    # students/high-school/general defaults
    return {"budget_fit": 0.45, "brand_match": 0.15, "performance": 0.20, "portability": 0.20}


def _performance_signal(product: Dict[str, Any]) -> float:
    text = (
        str(product.get("name") or "")
        + " "
        + " ".join([str(x) for x in (product.get("features") or [])])
    ).lower()
    score = 0.0
    if any(t in text for t in ("rtx", "geforce", "radeon", "gpu", "vram")):
        score += 1.0
    if any(t in text for t in ("i7", "i9", "ryzen 7", "ryzen 9", "ultra 7", "ultra 9")):
        score += 0.6
    if any(t in text for t in ("32gb", "24gb", "16gb ram")):
        score += 0.5
    return min(score, 2.0) / 2.0


def _portability_signal(product: Dict[str, Any]) -> float:
    text = (
        str(product.get("name") or "")
        + " "
        + " ".join([str(x) for x in (product.get("features") or [])])
    ).lower()
    score = 0.0
    if any(t in text for t in ('13"', '14"', "13.", "14.", "thin", "light")):
        score += 0.7
    if "macbook air" in text:
        score += 0.5
    return min(score, 1.0)


def _budget_fit_signal(price: float, budget: Dict[str, int | None]) -> float:
    bmin = budget.get("budget_min")
    bmax = budget.get("budget_max")
    if price <= 0:
        return 0.0
    if bmin is not None and bmax is not None and bmin <= price <= bmax:
        return 1.0
    if bmax is not None and price <= bmax:
        return 0.8
    if bmax is not None and price > bmax:
        over = max(1.0, float(price - bmax))
        return max(0.0, 1.0 - (over / max(float(bmax), 1.0)))
    if bmin is not None and price >= bmin:
        return 0.8
    return 0.5


def _score_anchor_candidate(
    product: Dict[str, Any],
    *,
    anchor: Dict[str, Any],
    budget: Dict[str, int | None],
    weights: Dict[str, float],
) -> float:
    try:
        price = float(product.get("price") or 0.0)
    except Exception:
        price = 0.0
    name = str(product.get("name") or "").lower()
    brand = str(anchor.get("brand_hint") or "").lower()
    brand_match = 1.0 if (brand and brand in name) else 0.0
    budget_fit = _budget_fit_signal(price, budget)
    perf = _performance_signal(product)
    portable = _portability_signal(product)
    return (
        (weights.get("budget_fit", 0.0) * budget_fit)
        + (weights.get("brand_match", 0.0) * brand_match)
        + (weights.get("performance", 0.0) * perf)
        + (weights.get("portability", 0.0) * portable)
    )


def _build_anchor_sections(
    *,
    images: List[Dict[str, Any]] | None,
    products: List[Dict[str, Any]],
    query: str,
    budget: Dict[str, int | None],
    use_case_key: str | None,
    buyer_persona: str | None,
) -> List[Dict[str, Any]]:
    imgs = [x for x in (images or []) if isinstance(x, dict)]
    if not imgs:
        return []
    sections: List[Dict[str, Any]] = []
    weights = _persona_rank_weights(use_case_key, buyer_persona)
    for idx, img in enumerate(imgs):
        # Off-domain image (e.g. produce) → do NOT fabricate a "Best 3 matches for this image" product
        # group; the separate off-domain banner explains it. Agnostic relevance check (profile tokens).
        try:
            from src.app.services.cv_triage_basic import classify_image_relevance
            _labels = img.get("labels") if isinstance(img.get("labels"), list) else []
            _cr = img.get("catalog_relevance") if isinstance(img.get("catalog_relevance"), dict) else {}
            # skip the "matches for this image" group when EITHER the relevance classifier says off_topic OR
            # an explicit off-domain flag is set (the classifier needs good CV labels; the flag is the backstop
            # so a mislabelled off-domain image can't still claim "Best 3 matches for this image" — screenshot 007).
            _off = (classify_image_relevance(_labels, str(img.get("ocr_text") or "")) == "off_topic"
                    or bool(img.get("off_domain")) or bool(_cr.get("off_domain"))
                    or str(img.get("image_relevance") or "").strip().lower() == "off_topic")
            if _off:
                continue
        except Exception:
            pass
        anchor = _image_anchor_hint(img, idx)
        scored: List[tuple[float, Dict[str, Any]]] = []
        for p in products:
            if not isinstance(p, dict):
                continue
            scored.append((_score_anchor_candidate(p, anchor=anchor, budget=budget, weights=weights), p))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [row[1] for row in scored[:3]]
        brand_hint = str(anchor.get("brand_hint") or "").lower()
        if brand_hint:
            def _is_apple_row(row: Dict[str, Any]) -> bool:
                txt = f"{str(row.get('name') or '')} {str(row.get('sku') or '')}".lower()
                return ("apple" in txt) or ("macbook" in txt) or txt.startswith("mb")

            if brand_hint == "apple":
                apple_rows = [row[1] for row in scored if _is_apple_row(row[1])]
                if apple_rows:
                    top = apple_rows[:3]
            elif brand_hint in {"lenovo", "dell", "hp", "asus", "acer", "msi", "microsoft", "samsung"}:
                windows_rows = [row[1] for row in scored if not _is_apple_row(row[1])]
                if windows_rows:
                    top = windows_rows[:3]
        if not top:
            continue
        bmin = budget.get("budget_min")
        bmax = budget.get("budget_max")
        budget_phrase = (
            f"${bmin:,}-${bmax:,}" if bmin is not None and bmax is not None
            else (f"under ${bmax:,}" if bmax is not None else (f"over ${bmin:,}" if bmin is not None else "your budget"))
        )
        uc = str(use_case_key or buyer_persona or anchor.get("use_case_hint") or "general").replace("_", " ")
        summary = (
            f"Closest catalog picks for your image + text, in {budget_phrase}. "
            f"Prioritized for {uc} on brand/form-factor and price fit."
        )
        sections.append(
            {
                "anchor_id": anchor.get("anchor_id"),
                "title": f"{anchor.get('title')} {'(' + str(anchor.get('brand_hint')) + ')' if anchor.get('brand_hint') else ''}".strip(),
                "source_image_hash": anchor.get("image_hash"),
                "anchor_hint": {
                    "brand": anchor.get("brand_hint"),
                    "use_case": anchor.get("use_case_hint"),
                    "ocr_excerpt": anchor.get("ocr_excerpt"),
                },
                "top_products": top,
                "summary": summary,
                "match_basis": ["budget_fit", "query_intent", "image_brand_hint", "persona_profile"],
            }
        )
    return sections


def _build_right_panel_contract(
    *,
    products: List[Dict[str, Any]],
    turn_intent: str,
    budget_viability: Dict[str, Any] | None,
    use_case_analysis: Dict[str, Any] | None,
    anchor_sections: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    if str(turn_intent or "").upper() == "SUPPORT_CLAIM":
        return {
            "mode": "support",
            "show_tiers": False,
            "summary": "Support mode active: troubleshooting, warranty, and escalation guidance.",
        }

    items: List[Dict[str, Any]] = [p for p in (products or []) if isinstance(p, dict)]
    if not items:
        return {"mode": "shopping", "show_tiers": False}

    prices = []
    for p in items:
        try:
            prices.append(float(p.get("price") or 0.0))
        except Exception:
            continue
    prices = [x for x in prices if x > 0]
    prices.sort()
    median_price = prices[len(prices) // 2] if prices else 0.0

    lower = []
    higher = []
    for p in items:
        try:
            px = float(p.get("price") or 0.0)
        except Exception:
            px = 0.0
        if px <= median_price:
            lower.append(p)
        else:
            higher.append(p)
    lower = lower[:4]
    higher = higher[:4]
    status = str((budget_viability or {}).get("status") or "unknown").lower()
    show_tiers = status in {"low", "high"} or bool(use_case_analysis and len(items) >= 4)
    return {
        "mode": "shopping",
        "show_tiers": bool(show_tiers),
        "anchor_sections": anchor_sections or [],
        "budget_status": status,
        "lower_tier": {
            "title": "Budget-fit options",
            "items": lower or items[:4],
            "explanation": "Prioritizes value, battery life, and practical everyday performance.",
        },
        "higher_tier": {
            "title": "Performance-fit options",
            "items": higher or items[:4],
            "explanation": "Prioritizes higher CPU/GPU headroom for heavier workloads.",
        },
    }


def _extract_brand_mentions(query: str) -> List[str]:
    q = str(query or "").lower()
    known = ("apple", "macbook", "dell", "lenovo", "asus", "hp", "acer", "msi", "microsoft", "surface", "samsung")
    out: List[str] = []
    for b in known:
        if b in q:
            mapped = "apple" if b == "macbook" else ("microsoft" if b == "surface" else b)
            if mapped not in out:
                out.append(mapped)
    return out


def _merge_material_nqe_answer(
    *, query: str, nqe_selection: Dict[str, Any] | None,
    recent_messages: List[Dict[str, Any]] | None,
    pending_clarification: Dict[str, Any] | None = None,
) -> str:
    """Resolve a bounded material answer against the turn that asked for it.

    NQE buttons submit their short label as the visible user message.  For slots that change
    authorization semantics, that label is not a standalone query: it must refine the preceding
    buyer request.  Only known question/option IDs are accepted; arbitrary button text is never
    promoted into hidden context.
    """
    selection = nqe_selection if isinstance(nqe_selection, dict) else {}
    pending = pending_clarification if isinstance(pending_clarification, dict) else {}
    # Compatibility for older callers/tests that supplied only browser history.
    # New runtime traffic persists this contract server-side for every material
    # clarification; history is never authoritative when pending state exists.
    if not pending and str(selection.get("question_id") or "").strip().lower() == "budget_scope":
        prior_query = ""
        for item in reversed(recent_messages or []):
            if not isinstance(item, dict) or str(item.get("role") or "").strip().lower() != "user":
                continue
            candidate = str(item.get("content") or "").strip()
            if candidate and candidate.casefold() != str(query or "").strip().casefold():
                prior_query = candidate
                break
        if prior_query:
            pending = {
                "version": 1,
                "state": "active",
                "question_id": "budget_scope",
                "question": "Is the stated budget total or per item?",
                "options": [
                    {"id": "total", "label": "Total budget"},
                    {"id": "per_unit", "label": "Per item"},
                ],
                "original_query": prior_query,
            }
    try:
        from src.app.services.clarification_state import reduce_clarification_turn

        reduced = reduce_clarification_turn(
            query=str(query or ""),
            nqe_selection=selection,
            pending=pending,
        )
        if reduced.relation in {"answer", "expired"}:
            return reduced.effective_query
    except Exception:
        pass
    qid = str(selection.get("question_id") or "").strip().lower()
    oid = str(selection.get("option_id") or "").strip().lower()
    # A buyer can answer the rendered question by typing instead of clicking its
    # option. Recognize only the canonical budget-scope grammar and only while
    # the server has an authoritative pending question. This preserves natural
    # chat UX without allowing arbitrary old messages to become hidden context.
    if not qid and str(pending.get("question_id") or "").strip().lower() == "budget_scope":
        try:
            from src.app.services.budget_grammar import classify_budget_scope

            inferred = classify_budget_scope(query)
        except Exception:
            inferred = "unknown"
        if inferred in {"total", "per_unit"}:
            qid, oid = "budget_scope", inferred
    if qid != "budget_scope" or oid not in {"total", "per_unit"}:
        return query

    prior_query = ""
    if str(pending.get("question_id") or "").strip().lower() == qid:
        allowed = {str(item).strip().lower() for item in (pending.get("allowed_option_ids") or [])}
        if oid in allowed:
            prior_query = str(pending.get("original_query") or "").strip()
    for item in reversed(recent_messages or []):
        if prior_query:
            break
        if not isinstance(item, dict) or str(item.get("role") or "").strip().lower() != "user":
            continue
        candidate = str(item.get("content") or "").strip()
        if candidate and candidate.casefold() != str(query or "").strip().casefold():
            prior_query = candidate
            break
    if not prior_query:
        return query

    scope_statement = (
        "The stated budget is the total budget for all requested units."
        if oid == "total"
        else "The stated budget is a per item budget."
    )
    return f"{prior_query} {scope_statement}"


def _include_adaptive_metadata(out: Dict[str, Any], source: Dict[str, Any]) -> None:
    """Copy only adaptive levers that actually ran; absence is a public contract."""
    for key in ("sales_response_nudge", "ranking_experiment", "storefront_emphasis"):
        value = source.get(key)
        if isinstance(value, dict):
            out[key] = value


def _extract_image_cv_signals(image_obj: Dict[str, Any] | None) -> Dict[str, Any]:
    from src.app.services.chat_image_normalization import extract_image_cv_signals

    return extract_image_cv_signals(image_obj)


def _extract_image_product_identity(image_obj: Dict[str, Any] | None) -> Dict[str, Any]:
    from src.app.services.chat_image_normalization import extract_image_product_identity

    return extract_image_product_identity(image_obj)


def _derive_image_security_posture(sig: Dict[str, Any] | None) -> Dict[str, Any]:
    s = sig if isinstance(sig, dict) else {}
    qr_detected = bool(s.get("qr_code_detected"))
    qr_external = bool(s.get("qr_external_url_detected"))
    qr_injection = bool(s.get("qr_prompt_injection"))
    ocr_injection = bool(s.get("ocr_prompt_injection"))
    manipulation = bool(s.get("manipulation_detected"))
    steg = bool(s.get("steg_suspicious"))
    adversarial = float(s.get("adversarial_score") or 0.0)
    encoded = bool(s.get("encoded_payload_detected"))
    polyglot = bool(s.get("polyglot_suspected"))
    ocr_uncertain = bool(s.get("ocr_low_confidence_uncertain"))
    analysis_pending = bool(
        s.get("analysis_pending") or s.get("vision_pending") or s.get("fast_triage_timeout")
    )
    analysis_degraded = bool(
        ocr_uncertain or s.get("vision_timeout") or s.get("ocr_timeout")
        or s.get("vision_error") or s.get("ocr_error")
    )
    security_risk = bool(
        qr_external or qr_injection or ocr_injection or manipulation or steg
        or adversarial >= 0.35 or encoded or polyglot
    )

    hard_lock = bool(
        polyglot
        or (
            qr_injection
            and (qr_external or ocr_injection)
            and (manipulation or steg or adversarial >= 0.75 or encoded)
        )
        or (qr_external and (manipulation or steg or adversarial >= 0.9))
    )
    needs_review = bool(
        hard_lock
        or qr_external
        or ocr_injection
        or steg
        or adversarial >= 0.5
        or encoded
    )
    degraded = bool(
        qr_detected
        or security_risk
    )
    if hard_lock:
        route = "lockdown"
        severity = "high"
        message = (
            "Image content looks unsafe (malicious QR/injection risk). "
            "Chat is temporarily locked for image-driven actions while we escalate to human review."
        )
    elif needs_review:
        route = "escalate"
        severity = "high"
        message = (
            "Image was flagged. I will continue with text-only recommendations and escalate security review in parallel."
        )
    elif degraded:
        route = "visual_sanitized"
        severity = "warn"
        message = (
            "Embedded or unverified image channels were ignored. Safe visual matching can continue."
        )
    elif analysis_pending:
        route = "analysis_pending"
        severity = "info"
        message = "Image analysis is still running. I will not use incomplete image evidence yet."
    elif analysis_degraded:
        route = "analysis_degraded"
        severity = "info"
        message = "Some image details could not be verified. Visual matches remain available, but uncertain text was ignored."
    else:
        route = "allow"
        severity = "info"
        message = ""
    return {
        "route": route,
        "severity": severity,
        "security_risk": security_risk,
        "analysis_degraded": analysis_degraded,
        "analysis_pending": analysis_pending,
        "image_untrusted": security_risk,
        "image_degraded_mode": bool((degraded or analysis_degraded) and not hard_lock),
        "needs_human_review": bool(needs_review),
        "chat_lockdown": bool(hard_lock),
        "warning_message": message,
    }
