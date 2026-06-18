"""Budget / brand advisor stage — extracted from recommend.py::suggest() (core/adapter split).

CORE mechanism: turn (query, results, constraints) into a deterministic, evidence-grounded
budget/brand verdict ("Yes, $1,800 covers these…", "No, that's short for gaming…") and the
human-readable assistant message — never copywriting, always derived from the actual result
prices + use-case floors. Pure builders: no DB, no request locals, no LLM.

ADAPTER (flavour): the use-case price floors, persona labels and gpu/brand vocabulary below are
electronics flavour. They are the Phase-2 profile-back target (a non-electronics vertical supplies
its own floors/labels via the StoreProfile) — which is why this module is intentionally NOT yet on
the no-flavour-in-core lint, exactly like recommend_image_hints.py / recommend_utils.py.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from src.app.services.recommend_utils import (
    _brand_display_name,
    _candidate_matches_brand,
    _extract_candidate_numeric_specs,
    _result_price_dollars,
)
from src.app.services.recommend_image_hints import _SUPPORTED_IMAGE_BRAND_HINTS
from src.app.services.use_case_advisor import get_use_case_min_price_floor



_USE_CASE_BUDGET_FLOORS: dict[str, int] = {
    # Minimum viable new-laptop price (AUD/USD rough floor) per workload tier
    "high_school": 400,
    "gaming_casual": 600, "gaming_competitive": 900, "gaming_light": 500,
    "gaming_aaa_heavy": 1200,
    "engineering_student": 1000, "architecture_student": 1000,
    "ai_ml_workstation": 1500, "data_science_student": 900,
    "content_creator": 900, "music_production": 800,
    "computer_science_student": 600, "design_student": 700,
    "university_general": 400, "note_taking_student": 350,
    "office_general": 350, "office_finance": 500, "office_executive": 600,
    "medical_student": 500, "law_student": 400,
}


def _persona_summary_label(persona: str | None, use_case: str | None) -> str:
    key = str(use_case or persona or "").strip().lower()
    labels = {
        "university_general": "uni work",
        "student": "student work",
        "high_school": "schoolwork",
        "office_general": "office work",
        "office_finance": "finance work",
        "office_executive": "professional work",
        "content_creator": "creative work",
        "content_creation": "creative work",
        "gaming": "gaming",
        "gaming_light": "light gaming",
        "gaming_competitive": "competitive gaming",
        "gaming_aaa_heavy": "AAA gaming",
        "ai_ml_workstation": "AI and coding work",
        "data_science_student": "coding and analysis",
        "engineering_student": "engineering work",
        "architecture_student": "design work",
        "medical_student": "study and research",
        "law_student": "study and reading",
    }
    if key in labels:
        return labels[key]
    if key.startswith("office_"):
        return "office work"
    if "student" in key:
        return "study"
    return ""


def _assess_budget_fitness(
    use_case: str | None, budget_min: float | None, budget_max: float | None,
) -> dict[str, Any]:
    """Compare stated budget against use-case minimum viable price.

    Returns: {status: 'ok'|'low'|'high', floor, advice}
    """
    if not use_case or not budget_max:
        return {"status": "unknown"}
    floor = get_use_case_min_price_floor(str(use_case)) or _USE_CASE_BUDGET_FLOORS.get(use_case)
    if not floor:
        return {"status": "unknown"}
    bmax = float(budget_max)
    if bmax < floor * 0.85:
        return {
            "status": "low",
            "floor": floor,
            "gap": round(floor - bmax),
            "alternatives": [
                "show_best_within_budget",
                f"raise_budget_to_{int(floor)}",
                "consider_refurbished_or_previous_gen",
            ],
            "advice": (
                f"For {use_case.replace('_', ' ')}, most new laptops start around ${floor}. "
                f"At ${int(bmax)} you'll be looking at older or refurbished models. "
                f"Would you like the best option at your budget, or would you consider raising it a bit?"
            ),
        }
    if bmax > floor * 3.0:
        return {
            "status": "high",
            "floor": floor,
            "excess": round(bmax - floor * 2),
            "alternatives": [
                "show_best_value_pick",
                "show_balanced_mid_tier",
                "show_premium_only_if_needed",
            ],
            "advice": (
                f"Your budget is generous for {use_case.replace('_', ' ')}. "
                f"You won't feel much real-world difference beyond ~${floor * 2}. "
                f"I can show a great-value pick and a premium option so you're not overpaying."
            ),
        }
    return {"status": "ok", "floor": floor}


def _build_minimum_recommended_tiers(
    results: list[dict] | None,
    *,
    budget_min: float | None,
    budget_max: float | None,
    use_case: str | None,
    query: str | None = None,
) -> dict[str, Any]:
    rows = [r for r in (results or []) if isinstance(r, dict)]
    if not rows:
        return {"minimum": [], "recommended": [], "show_split": False}

    priced: list[tuple[dict, float]] = []
    for r in rows:
        try:
            p = float(r.get("price") or (float(r.get("price_cents") or 0.0) / 100.0))
        except Exception:
            p = 0.0
        priced.append((r, p))
    priced_valid = [x for x in priced if x[1] > 0]
    prices = sorted([p for _, p in priced_valid])
    median = prices[len(prices) // 2] if prices else 0.0

    def _spec_strength(r: dict) -> float:
        specs = r.get("specs") if isinstance(r.get("specs"), dict) else {}
        score = 0.0
        try:
            ram = float(specs.get("ram_gb") or 0)
            if ram >= 32:
                score += 2.0
            elif ram >= 16:
                score += 1.2
            elif ram >= 8:
                score += 0.6
        except Exception:
            pass
        gpu = str(specs.get("gpu") or "").lower()
        if any(tok in gpu for tok in ("rtx", "radeon", "geforce", "arc")):
            score += 1.5
        cpu = str(specs.get("cpu") or "").lower()
        if any(tok in cpu for tok in ("i7", "i9", "ryzen 7", "ryzen 9", "ultra 7", "ultra 9")):
            score += 1.0
        try:
            s = float(r.get("score_norm") or 0.0) / 100.0
            score += max(0.0, min(1.0, s))
        except Exception:
            pass
        return score

    minimum: list[dict] = []
    recommended: list[dict] = []
    for r, px in priced:
        within_budget = True
        if budget_min is not None and px > 0:
            within_budget = within_budget and (px >= float(budget_min))
        if budget_max is not None and px > 0:
            within_budget = within_budget and (px <= float(budget_max))
        rec_like = (_spec_strength(r) >= 2.2) or (px > 0 and px >= median)
        if within_budget and not rec_like:
            minimum.append(r)
        elif rec_like:
            recommended.append(r)
        else:
            minimum.append(r)

    if not minimum:
        minimum = [r for r, _ in priced][:3]
    if not recommended:
        recommended = [r for r, _ in sorted(priced, key=lambda x: _spec_strength(x[0]), reverse=True)][:3]

    minimum = minimum[:3]
    recommended = recommended[:3]
    q = str(query or "").lower()
    explicit_split = any(tok in q for tok in ("minimum", "recommended", "min specs", "recommended specs"))
    show_split = (bool(use_case) or explicit_split) and (len(minimum) > 0 and len(recommended) > 0)
    return {
        "minimum": minimum,
        "recommended": recommended,
        "show_split": show_split,
        "minimum_explanation": "Meets practical baseline with better value and battery/cost balance.",
        "recommended_explanation": "Adds performance headroom for heavier tasks and longer-term use.",
    }


def _budget_reasoning_requested(query: str | None) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    if "why" in q and any(tok in q for tok in ("budget", "enough", "go higher", "worth", "value")):
        return True
    return any(
        phrase in q
        for phrase in (
            "is 1800 enough",
            "is $",
            "is enough",
            "should i go higher",
            "go higher",
            "worth it",
            "better value",
            "good enough",
            "overkill",
        )
    )


def _build_budget_reasoning_note(query: str | None, results: list[dict], constraints: dict) -> str:
    if not _budget_reasoning_requested(query):
        return ""
    budget_max = constraints.get("budget_max")
    try:
        budget_cap = float(budget_max) if budget_max is not None else 0.0
    except Exception:
        budget_cap = 0.0
    if budget_cap <= 0:
        return ""

    use_case = str(constraints.get("use_case") or "").strip().replace("_", " ")
    bf = constraints.get("budget_fitness") if isinstance(constraints.get("budget_fitness"), dict) else {}
    status = str(bf.get("status") or "").strip().lower()
    floor = bf.get("floor")
    try:
        floor_val = float(floor) if floor is not None else 0.0
    except Exception:
        floor_val = 0.0

    prices = [p for p in (_result_price_dollars(r) for r in (results or [])) if isinstance(p, (int, float))]
    if not prices:
        return ""
    cheapest = min(float(p) for p in prices)
    strongest = _result_price_dollars((results or [None])[0]) or cheapest
    label = use_case or "this use case"

    if status == "high":
        return (
            f"Yes, ${int(budget_cap):,} is more than enough for {label}. "
            f"A strong fit is already available around ${int(round(strongest)):,}, so going higher is mostly about premium headroom rather than necessity."
        )
    if status == "ok":
        if floor_val and budget_cap >= floor_val * 1.45:
            return (
                f"Yes, ${int(budget_cap):,} is a strong budget for {label}. "
                f"You already have viable options from about ${int(round(cheapest)):,}, and going higher would mostly buy extra performance headroom or nicer build/display quality."
            )
        return (
            f"Yes, ${int(budget_cap):,} is workable for {label}. "
            f"The current shortlist starts around ${int(round(cheapest)):,}; going a bit higher would mainly help if you want more long-term headroom."
        )
    return ""


def _build_brand_budget_answer(query: str, results: list[dict], constraints: dict) -> str:
    import re as _re_bba
    q_low = str(query or "").lower()
    asks_budget = any(
        tok in q_low for tok in (
            "enough", "budget", "under $", "between $", "can i get one for", "is $",
            "price", "cheap", "cheapest", "only have", "is that enough", "is this enough",
            "will $", "would $", "can $", "could $", "will this cover", "would this cover",
            "can i afford", "do i have enough", "is that too", "too expensive",
            "worth it", "within budget", "fits my budget",
        )
    )
    if not asks_budget:
        return ""

    def _extract_budget_value(text: str) -> float | None:
        patterns = (
            r"[\$€£]\s*(\d[\d,]+)",
            r"\b(?:only have|have|budget(?:\s+is|\s+of)?|under|below|max(?:imum)?|up to|around|about|for)\s+\$?\s*(\d[\d,]+)\b",
            r"\b(\d[\d,]{2,5})\s*(?:dollars|bucks)\b",
        )
        for pattern in patterns:
            match = _re_bba.search(pattern, text)
            if not match:
                continue
            try:
                value = float(match.group(1).replace(",", ""))
            except Exception:
                continue
            if 100 <= value <= 10000:
                return value
        return None

    def _generic_budget_floor(use_case_text: str, query_text: str) -> tuple[int, str]:
        combined = f"{use_case_text} {query_text}".strip().lower()
        if any(tok in combined for tok in ("gaming", "esports", "rtx", "fps")):
            return 1200, "gaming laptop"
        if any(tok in combined for tok in ("creator", "video editing", "render", "3d", "cad", "architecture", "engineering", "ai", "ml")):
            return 1200, "creator or engineering laptop"
        if any(tok in combined for tok in ("school", "student", "high school", "university", "college")):
            return 700, "school laptop"
        if any(tok in combined for tok in ("business", "office", "corporate", "work")):
            return 800, "business laptop"
        return 600, "laptop"

    # ── Extract budget from query text when not already in constraints ──────
    # Handles ranges ("$1200 to $1800"), single values ("under $1800"), and
    # bare number ranges ("1200 to 1800", "1200-1800 dollars").
    if not constraints.get("budget_max") and not constraints.get("_request_budget_max"):
        import re as _re_bba2
        _budget_extracted = False
        # Range: "$X to $Y" / "$X - $Y" / "X to Y" / "X-Y" — take Y as max, X as min
        _rng = _re_bba2.search(
            r"[\$€£]?\s*(\d{3,5})\s*(?:to|and|-)\s*[\$€£]?\s*(\d{3,5})\b", q_low
        )
        if _rng:
            try:
                _lo = float(_rng.group(1).replace(",", ""))
                _hi = float(_rng.group(2).replace(",", ""))
                if 100 < _lo < _hi <= 10000:
                    constraints = dict(constraints)
                    constraints["budget_min"] = _lo
                    constraints["budget_max"] = _hi
                    _budget_extracted = True
            except Exception:
                pass
        if not _budget_extracted:
            # Single value: "$1800", "under 1800 dollars", "budget of 1800"
            _m = _re_bba2.search(r"[\$€£]\s*(\d[\d,]+)", q_low)
            if not _m:
                _m = _re_bba2.search(r"\b(\d{3,5})\s*(?:dollars|bucks)\b", q_low)
            if _m:
                try:
                    _extracted = float(_m.group(1).replace(",", ""))
                    if _extracted > 100:
                        constraints = dict(constraints)
                        constraints["budget_max"] = _extracted
                except Exception:
                    pass

    # ── Corporate / business use case deterministic answer ──────────────────
    _is_corporate = any(
        tok in q_low for tok in (
            "corporate", "business", "office", "work laptop", "work use",
            "enterprise", "professional use", "company",
        )
    )
    _use_case = str(constraints.get("use_case") or "").lower()
    if not _is_corporate and "office" in _use_case or "corporate" in _use_case:
        _is_corporate = True
    if _is_corporate:
        _bmax = float(constraints.get("budget_max") or constraints.get("_request_budget_max") or 0)
        if _bmax > 0 and results:
            def _cp(r: dict) -> float:
                try:
                    return float((r or {}).get("price_cents") or 0) / 100.0
                except Exception:
                    return 0.0
            _prices = [_cp(r) for r in results if _cp(r) > 0]
            if _prices:
                _cheapest = min(_prices)
                _brands_seen = list(dict.fromkeys(
                    str((r or {}).get("brand") or "").title()
                    for r in results[:3] if (r or {}).get("brand")
                ))
                _brand_str = " and ".join(_brands_seen[:2]) if _brands_seen else "business-class"
                if _cheapest > _bmax:
                    return (
                        f"For ${int(_bmax):,} in business use, the nearest options start around "
                        f"${int(round(_cheapest)):,} — here are the closest matches."
                    )
                return (
                    f"For ${int(_bmax):,} in corporate use, you're in {_brand_str} territory — "
                    "solid build quality, business warranty, and good port selection. "
                    f"Here are your top {min(len(results), 3)} options."
                )
    brand_hint = str(
        constraints.get("_strict_image_brand_hint")
        or constraints.get("_inferred_image_brand")
        or constraints.get("_request_brand_hint")
        or ""
    ).strip().lower()
    if brand_hint not in _SUPPORTED_IMAGE_BRAND_HINTS:
        req_brands = [str(b).strip().lower() for b in (constraints.get("brands") or []) if str(b).strip()]
        for req_brand in req_brands:
            if req_brand in _SUPPORTED_IMAGE_BRAND_HINTS:
                brand_hint = req_brand
                break
    if brand_hint not in _SUPPORTED_IMAGE_BRAND_HINTS:
        result_names = " ".join(str((row or {}).get("name") or "") for row in (results or [])[:3]).lower()
        if any(tok in q_low for tok in ("macbook", "mac book", "apple")) or "macbook" in result_names:
            brand_hint = "apple"
        else:
            for fallback_brand in ("msi", "asus", "lenovo", "dell", "hp", "alienware", "microsoft"):
                if fallback_brand in q_low or fallback_brand in result_names:
                    brand_hint = fallback_brand
                    break
    if brand_hint not in _SUPPORTED_IMAGE_BRAND_HINTS:
        # ── Generic budget answer when no brand is identified ──
        # e.g. "Is $1,800 enough for a gaming laptop?" → yes/no based on result prices
        budget_max_generic = (
            constraints.get("budget_max")
            or constraints.get("_request_budget_max")
            or ((constraints.get("_price_filter_meta") or {}).get("budget_max") if isinstance(constraints.get("_price_filter_meta"), dict) else None)
        )
        if budget_max_generic and results:
            def _gp(row: dict) -> float:
                try:
                    c = float((row or {}).get("price_cents") or 0)
                    return c / 100.0 if c > 0 else 0.0
                except Exception:
                    return 0.0
            valid_prices = [_gp(r) for r in results if _gp(r) > 0]
            if valid_prices:
                cheapest = min(valid_prices)
                cap = float(budget_max_generic)
                price_meta = constraints.get("_price_filter_meta") if isinstance(constraints.get("_price_filter_meta"), dict) else {}
                fallback = str(price_meta.get("fallback") or "").strip().lower()
                over = cheapest > cap or "nearest_above_budget" in fallback
                use_case_label = str(constraints.get("use_case") or "").replace("_", " ").strip()
                category_label = use_case_label or "laptops"
                if over:
                    return (
                        f"Your ${int(cap):,} budget is a little short — the closest options start around "
                        f"${int(round(cheapest)):,}. I've shown you the nearest matches."
                    )
                return (
                    f"Yes, ${int(cap):,} covers these {category_label} options, "
                    f"with models starting from ${int(round(cheapest)):,}."
                )
            else:
                # Products found but prices unavailable — still answer the budget question
                cap = float(budget_max_generic)
                use_case_label = str(constraints.get("use_case") or "").replace("_", " ").strip()
                n = len(results)
                plural = "s" if n != 1 else ""
                return (
                    f"Yes, ${int(cap):,} should cover these options. "
                    f"I found {n} {use_case_label or 'laptop'}{plural} in that range."
                )
        return ""
    budget_max = (
        constraints.get("budget_max")
        or constraints.get("_request_budget_max")
        or ((constraints.get("_price_filter_meta") or {}).get("budget_max") if isinstance(constraints.get("_price_filter_meta"), dict) else None)
    )
    if budget_max is None:
        return ""
    def _row_price(row: dict) -> float:
        try:
            cents = float((row or {}).get("price_cents") or 0)
            return cents / 100.0 if cents > 0 else 0.0
        except Exception:
            return 0.0

    try:
        brand_rows = [
            row for row in (results or [])
            if isinstance(row, dict) and _candidate_matches_brand(row, [brand_hint])
        ]
        source_rows = brand_rows or list(results or [])
        first_price = min(_row_price(row) for row in source_rows if _row_price(row) > 0)
    except Exception:
        first_price = 0.0
    if first_price <= 0:
        return ""
    price_meta = constraints.get("_price_filter_meta") if isinstance(constraints.get("_price_filter_meta"), dict) else {}
    fallback = str(price_meta.get("fallback") or "").strip().lower()
    budget_cap = float(budget_max or 0)
    over_budget = first_price > budget_cap or "nearest_above_budget" in fallback
    brand_label = _brand_display_name(brand_hint)
    if brand_hint == "apple":
        if over_budget:
            return (
                f"No, not for Apple in the current catalog. The nearest Apple option starts around "
                f"${int(round(first_price)):,}."
            )
        return f"Yes, this budget reaches Apple options starting around ${int(round(first_price)):,}."
    brand_has_match = any(_candidate_matches_brand(row, [brand_hint]) for row in (results or []))
    if over_budget:
        return (
            f"No, not for {brand_label} at this budget. The nearest "
            f"{brand_label if brand_has_match else 'similar'} option starts around ${int(round(first_price)):,}."
        )
    return f"Yes, this budget reaches {brand_label if brand_has_match else 'similar'} options starting around ${int(round(first_price)):,}."


def _build_brand_budget_answer_v2(query: str, results: list[dict], constraints: dict) -> str:
    q_low = str(query or "").lower()
    asks_budget = any(
        tok in q_low for tok in (
            "enough", "budget", "under $", "between $", "can i get one for", "is $",
            "price", "cheap", "cheapest", "only have", "is that enough", "is this enough",
            "will $", "would $", "can $", "could $", "will this cover", "would this cover",
            "can i afford", "do i have enough", "is that too", "too expensive",
            "worth it", "within budget", "fits my budget",
        )
    )
    if not asks_budget:
        return ""

    def _extract_budget_value(text: str) -> float | None:
        """Return the budget ceiling from text. For ranges ($X to $Y) returns Y (the max)."""
        import re as _re_bba
        # Range pattern first — "$1200 to $1800" or "1200 to 1800" → return 1800 (the max)
        rng = _re_bba.search(r"[\$€£]?\s*(\d{3,5})\s*(?:to|and|-)\s*[\$€£]?\s*(\d{3,5})\b", text)
        if rng:
            try:
                lo, hi = float(rng.group(1)), float(rng.group(2))
                if 100 < lo < hi <= 10000:
                    return hi  # caller wants the ceiling / budget_max
            except Exception:
                pass
        patterns = (
            r"[\$€£]\s*(\d[\d,]+)",
            r"\b(?:only have|have|budget(?:\s+is|\s+of)?|under|below|max(?:imum)?|up to|around|about|for)\s+\$?\s*(\d[\d,]+)\b",
            r"\b(\d[\d,]{2,5})\s*(?:dollars|bucks)\b",
        )
        for pattern in patterns:
            match = _re_bba.search(pattern, text)
            if not match:
                continue
            try:
                value = float(match.group(1).replace(",", ""))
            except Exception:
                continue
            if 100 <= value <= 10000:
                return value
        return None

    def _generic_budget_floor(use_case_text: str, query_text: str) -> tuple[int, str]:
        combined = f"{use_case_text} {query_text}".strip().lower()
        if any(tok in combined for tok in ("gaming", "esports", "rtx", "fps")):
            return 900, "gaming laptop"
        if any(tok in combined for tok in ("creator", "video editing", "render", "3d", "cad", "architecture", "engineering", "ai", "ml")):
            return 1200, "creator or engineering laptop"
        if any(tok in combined for tok in ("school", "student", "high school", "university", "college")):
            return 700, "school laptop"
        if any(tok in combined for tok in ("business", "office", "corporate", "work")):
            return 800, "business laptop"
        return 600, "laptop"

    budget_max_generic = (
        constraints.get("budget_max")
        or constraints.get("_request_budget_max")
        or ((constraints.get("_price_filter_meta") or {}).get("budget_max") if isinstance(constraints.get("_price_filter_meta"), dict) else None)
        or _extract_budget_value(q_low)
    )
    if budget_max_generic and results:
        def _row_price(row: dict) -> float:
            try:
                cents = float((row or {}).get("price_cents") or 0)
                return cents / 100.0 if cents > 0 else 0.0
            except Exception:
                return 0.0
        valid_prices = [_row_price(r) for r in results if _row_price(r) > 0]
        if valid_prices:
            cheapest = min(valid_prices)
            cap = float(budget_max_generic)
            price_meta = constraints.get("_price_filter_meta") if isinstance(constraints.get("_price_filter_meta"), dict) else {}
            fallback = str(price_meta.get("fallback") or "").strip().lower()
            use_case_label = str(constraints.get("use_case") or "").replace("_", " ").strip()
            category_label = use_case_label or "laptops"
            gaming_like = any(tok in q_low for tok in ("gaming", "esports", "fps")) or "gaming" in use_case_label.lower()
            if gaming_like:
                gaming_ready_rows = [
                    row for row in (results or [])
                    if bool(_extract_candidate_numeric_specs(row).get("has_dedicated_gpu"))
                ]
                if not gaming_ready_rows:
                    return (
                        f"No, ${int(cap):,} is below a comfortable gaming-laptop budget in this catalog. "
                        "The machines under that cap are better for school or general work than modern gaming."
                    )
            if cheapest > cap or "nearest_above_budget" in fallback:
                return f"No, ${int(cap):,} is a little short. The closest {category_label} options start around ${int(round(cheapest)):,}."
            return f"Yes, ${int(cap):,} covers these {category_label} options, with models starting from ${int(round(cheapest)):,}."
    if budget_max_generic:
        cap = float(budget_max_generic)
        use_case_label = str(constraints.get("use_case") or "").replace("_", " ").strip()
        floor, category_label = _generic_budget_floor(use_case_label, q_low)
        label = use_case_label or category_label
        if cap < floor:
            return f"No, ${int(cap):,} is below a comfortable starting point for a {label}. Aim for around ${floor:,}+ or expect major trade-offs."
        if cap < int(floor * 1.35):
            return f"Yes, but ${int(cap):,} is entry-level for a {label}. Prioritise 16GB RAM, 512GB storage, and a real GPU if gaming matters."
        return f"Yes, ${int(cap):,} is a workable budget for a {label}. You should be able to get a solid fit without stretching too far."
    return _build_brand_budget_answer(query, results, constraints)


def _deterministic_assistant_message(query: str, results: list[dict], constraints: dict, brand_budget_answer: str = "") -> str | None:
    if not results:
        # No in-budget/in-catalog match → RECOVERY answer (CRAG): never a dead end
        # and never empty. Always offer an explicit upgrade path. This is also the
        # never-empty safety net for the main path (used at the `if not assistant_message`
        # fallback) so a budget question on a thin result set still gets a verdict.
        _bmax = constraints.get("budget_max")
        _bmin = constraints.get("budget_min")
        _brands = constraints.get("brands") or constraints.get("brand_hints") or []
        try:
            _brand_txt = f" {str(_brands[0]).upper()}" if _brands else ""
        except Exception:
            _brand_txt = ""
        if _bmax is not None:
            _band = f" under ${int(_bmax):,}"
        elif _bmin is not None:
            _band = f" above ${int(_bmin):,}"
        else:
            _band = ""
        _path = ("You can raise your budget, allow other brands, or I can show the "
                 "nearest in-stock options.")
        if brand_budget_answer:
            return f"{brand_budget_answer.rstrip()} {_path}"
        return f"I couldn't find an in-stock{_brand_txt} match{_band}. {_path}"
    budget_min = constraints.get("budget_min")
    budget_max = constraints.get("budget_max")

    # ── Persona-aware humanization ────────────────────────────────────────────
    shopper_intent = constraints.get("shopper_intent") if isinstance(constraints.get("shopper_intent"), dict) else {}
    persona = (
        str(shopper_intent.get("persona") or "").strip().lower()
        or str(constraints.get("buyer_persona") or "").strip().lower()
        or str(constraints.get("inferred_persona") or "").strip().lower()
    )
    urgency = str(shopper_intent.get("urgency") or "").strip().lower()
    bundle_receptivity = str(shopper_intent.get("bundle_receptivity") or "").strip().lower()
    use_case = str(constraints.get("use_case") or "").strip().lower()

    # Persona-specific opening phrase
    opening = ""
    if persona == "gamer" or use_case in ("gaming", "gaming_casual", "gaming_competitive", "gaming_aaa_heavy", "gaming_light"):
        opening = "Great news for your gaming setup — "
    elif persona == "student" or "student" in use_case or "university" in use_case:
        opening = "Here are some great student-friendly options — "
    elif persona == "corporate" or use_case.startswith("office_"):
        opening = "For your work and productivity needs, "
    elif persona == "creative" or use_case in ("content_creator", "content_creation"):
        opening = "For your creative workflow, "
    elif persona == "traveler" or "travel" in use_case:
        opening = "Keeping it lightweight and portable for you — "
    elif persona == "job_hunter":
        opening = "To make a great first impression — "
    elif use_case in ("ai_ml_workstation", "data_science_student", "engineering_student", "architecture_student"):
        opening = "For your technical workload, "
    elif use_case in ("medical_student", "law_student"):
        opening = "For your studies, "

    # Urgency note
    urgency_note = ""
    if urgency in ("high", "immediate", "urgent"):
        urgency_note = " All of these are in stock and ready for quick dispatch."
    elif urgency == "medium":
        urgency_note = " All of these are currently in stock."

    # Closing — bundle-aware vs standard
    if bundle_receptivity in ("high", "yes", "true"):
        closing = " Want to see the full list, compare them, or check compatible bundles?"
    else:
        closing = " Want a detailed list or comparison?"

    # Core count message (pluralised, comma-formatted budget)
    n = len(results)
    match_plural = "es" if n != 1 else ""   # "matches"
    option_plural = "s" if n != 1 else ""   # "options"
    if budget_min is not None and budget_max is not None:
        core = f"found {n} match{match_plural} between ${int(budget_min):,} and ${int(budget_max):,}"
    elif budget_max is not None:
        core = f"found {n} option{option_plural} under ${int(budget_max):,}"
    elif budget_min is not None:
        core = f"found {n} option{option_plural} above ${int(budget_min):,}"
    else:
        core = f"found {n} option{option_plural} that match your criteria"

    top_lines: list[str] = []
    try:
        def _display_name(row: dict) -> str:
            specs = (row or {}).get("specs")
            if isinstance(specs, dict):
                label = str(specs.get("display_name") or "").strip()
                subtitle = str(specs.get("subtitle") or "").strip()
                if subtitle:
                    storage = ""
                    try:
                        m = re.search(r"\[[^\]]+\]", subtitle)
                        storage = m.group(0) if m else ""
                    except Exception:
                        storage = ""
                    if storage:
                        return f"{label} {storage}".strip()
                if label:
                    return label
            return str((row or {}).get("name") or "").strip()

        for row in (results or [])[:2]:
            name = _display_name(row)
            if not name:
                continue
            price_cents = (row or {}).get("price_cents")
            try:
                price_text = f" (${int(round(float(price_cents or 0) / 100.0)):,})" if float(price_cents or 0) > 0 else ""
            except Exception:
                price_text = ""
            top_lines.append(f"{name}{price_text}")
    except Exception:
        top_lines = []

    core_line = f"I've {core}."
    if opening:
        core_line = f"{opening}I've {core}."

    persona_label = _persona_summary_label(persona, use_case)
    fit_line = ""
    if top_lines:
        if len(top_lines) == 1:
            picks = top_lines[0]
        else:
            picks = ", ".join(top_lines[:-1]) + f" and {top_lines[-1]}"
        fit_line = f"Best fits for {persona_label}: {picks}." if persona_label else f"Best fits here: {picks}."
    budget_reasoning = _build_budget_reasoning_note(query, results, constraints)

    parts: list[str] = []
    if brand_budget_answer:
        parts.append(brand_budget_answer)
        if budget_reasoning:
            parts.append(budget_reasoning)
        if fit_line:
            parts.append(fit_line)
    else:
        parts.append(core_line)
        if budget_reasoning:
            parts.append(budget_reasoning)
        if fit_line:
            parts.append(fit_line)
    if urgency_note:
        parts.append(urgency_note.strip())
    parts.append(closing.strip())
    return " ".join(p for p in parts if p).strip()
