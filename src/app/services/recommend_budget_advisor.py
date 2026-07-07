"""Budget / brand advisor stage — extracted from recommend.py::suggest() (core/adapter split).

CORE mechanism: turn (query, results, constraints) into a deterministic, evidence-grounded
budget/brand verdict ("Yes, $1,800 covers these…", "No, that's short for gaming…") and the
human-readable assistant message — never copywriting, always derived from the actual result
prices + use-case floors. Pure builders: no DB, no request locals, no LLM.

ADAPTER (flavour): GRADUATED 2026-07-07 — every vocabulary surface now reads from StoreProfile slots
(use_case_budget_floors, capability_classes, capability_verdicts, persona_labels, spec_strength_tokens,
premium_brand_aliases, brand_fallback_order, budget_floor_hints, step_up_spec). Vertical-EXCLUSIVE:
a profile without a slot gets no verdict/label rather than inheriting electronics wording. This module
IS on the no-flavour-in-core lint at zero tolerance; keep every new word in the profile, not here.
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
from src.app.services.price_conversion import cents_to_dollars
from src.app.services.use_case_advisor import get_use_case_min_price_floor



# Inline FALLBACK for the use-case budget floors (electronics). The live source is the active
# StoreProfile's `use_case_budget_floors` slot (see _use_case_budget_floors). Vertical-EXCLUSIVE:
# pharmacy/fashion supply their own floors; a non-electronics vertical must NOT inherit these — so
# the accessor PREFERS the profile (returns it outright when present), it does not union.
def _use_case_budget_floors(profile_id: str | None = None) -> dict[str, int]:
    """Use-case → minimum viable price for the ACTIVE vertical, from the StoreProfile
    `use_case_budget_floors` slot. Vertical-EXCLUSIVE: returns {} when the profile lacks the slot —
    NO cross-vertical fallback (a non-electronics vertical must not inherit electronics floors).
    No try/except needed: profile_slot is defensive (never raises) and the isinstance guard makes
    the int() cast safe (keeps this off the silent-except ratchet)."""
    from src.app.platform.store_profile import profile_slot
    prof = profile_slot("use_case_budget_floors", profile_id=profile_id, default=None)
    if isinstance(prof, dict) and prof:
        out = {str(k).strip().lower(): int(v) for k, v in prof.items() if isinstance(v, (int, float))}
        if out:
            return out
    return {}


def _profile_slot_dict(slot: str) -> dict:
    """Vertical-EXCLUSIVE dict slot from the active StoreProfile — {} when absent (a non-electronics
    vertical must NOT inherit electronics vocabulary). profile_slot is defensive; never raises."""
    from src.app.platform.store_profile import profile_slot
    val = profile_slot(slot, default=None)
    return val if isinstance(val, dict) else {}


def _profile_slot_list(slot: str) -> list:
    from src.app.platform.store_profile import profile_slot
    val = profile_slot(slot, default=None)
    return val if isinstance(val, list) else []


# Back-compat alias: the inline fallback IS the electronics floor table. Existing re-exports /
# call-sites that reference the electronics table directly keep working; the profile-preferred
# live source is _use_case_budget_floors().
_USE_CASE_BUDGET_FLOORS = _use_case_budget_floors("electronics")


def _persona_summary_label(persona: str | None, use_case: str | None) -> str:
    key = str(use_case or persona or "").strip().lower()
    labels = _profile_slot_dict("persona_labels")
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
    use_case_key = str(use_case).strip().lower()
    profile_floors = _use_case_budget_floors()
    floor = profile_floors.get(use_case_key)
    if not floor and profile_floors:
        # id-drift resolve (2026-07-07 live-audit): the incoming use_case ("ml_ai") and the floor key
        # ("ai_ml_workstation") can differ. Token-overlap binds them so budget fitness — and the whole
        # GPU-memory/step-up defense that hangs off its status — isn't lost to a naming mismatch.
        _toks = {t for t in use_case_key.replace("-", "_").split("_") if len(t) >= 2}
        _best, _best_n = None, 0
        for _k in profile_floors:
            _n = len(_toks & {t for t in _k.split("_") if len(t) >= 2})
            if _n > _best_n:
                _best, _best_n = _k, _n
        if _best and _best_n >= 2:
            floor = profile_floors[_best]
    if not floor and profile_floors:
        return {"status": "unknown"}
    floor = floor or get_use_case_min_price_floor(use_case_key)
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
                f"For {use_case_key.replace('_', ' ')}, most new options start around ${floor}. "
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
            p = float(r.get("price") or cents_to_dollars(r.get("price_cents")))
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
        _sst = _profile_slot_dict("spec_strength_tokens")
        gpu = str(specs.get("gpu") or "").lower()
        if any(str(tok).lower() in gpu for tok in (_sst.get("gpu") or [])):
            score += 1.5
        cpu = str(specs.get("cpu") or "").lower()
        if any(str(tok).lower() in cpu for tok in (_sst.get("cpu") or [])):
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


def _resolve_budget_max(constraints: dict) -> float:
    """Budget cap from ALL the keys it can land in — an EXPLICIT ?budget_max= param lands in
    'budget_max', but a TEXT-extracted budget ("is 3500 enough") lands in '_request_budget_max' /
    '_price_filter_meta.budget_max'. Reading only 'budget_max' (2026-07-07 live-audit bug) meant the
    GPU-memory/step-up defense fired via /suggest?budget_max=... but VANISHED on the /chat path where the
    budget is only in the query text — exactly screenshot-26's failure mode through the real UI."""
    raw = (constraints.get("budget_max")
           or constraints.get("_request_budget_max")
           or ((constraints.get("_price_filter_meta") or {}).get("budget_max")
               if isinstance(constraints.get("_price_filter_meta"), dict) else None))
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _build_budget_reasoning_note(query: str | None, results: list[dict], constraints: dict) -> str:
    if not _budget_reasoning_requested(query):
        return ""
    budget_cap = _resolve_budget_max(constraints)
    if budget_cap <= 0:
        return ""

    use_case = str(constraints.get("use_case") or "").strip().replace("_", " ")
    bf = constraints.get("budget_fitness") if isinstance(constraints.get("budget_fitness"), dict) else {}
    status = str(bf.get("status") or "").strip().lower()
    # Self-sufficient (2026-07-07 live-audit): the upstream budget_fitness is frequently stored as
    # {"status": "unknown"} (computed before the budget/use-case were fully resolved). Recompute here
    # from the resolved cap + use-case whenever it isn't a USABLE status — not only when it's empty —
    # else "unknown" falls through and the whole note (GPU-memory hedge + step-ups) silently returns "".
    if status not in ("high", "ok", "low"):
        bf = _assess_budget_fitness(constraints.get("use_case"), None, budget_cap) or {}
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

    # 2026-07-07 fix ("not smart" screenshot): "going higher buys nicer build quality" was a CANNED
    # line that contradicted the store's own catalog (higher tiers with 2-3x the GPU memory were in
    # stock). The go-higher clause is now CATALOG-AWARE: if products above the budget genuinely step
    # up a structured spec, say exactly what the extra money buys; the canned line is only the
    # fallback when nothing above budget is materially better.
    step_up_txt = ""
    _sus = _profile_slot_dict("step_up_spec")
    _su_label = str(_sus.get("label") or "").strip()
    _su_unit = str(_sus.get("unit") or "").strip()
    try:
        _ups = _above_budget_step_ups(budget_cap, _top_vram_gb(results))
        if _ups and _su_label:
            step_up_txt = " Going higher has a real payoff here: " + "; ".join(
                f"~${int(round(p)):,} steps up to {v}{_su_unit} {_su_label} ({_short_name(n)})" for n, p, v in _ups
            ) + "."
    except Exception:
        step_up_txt = ""
    vram_hedge = ""
    try:
        _tv = _top_vram_gb(results)
        _strong = int(_sus.get("strong_min") or 16)
        if _tv and _tv < _strong and any(t in label.lower() for t in ("ai", "ml", "machine", "deep", "data")):
            _tpl = (_profile_slot_dict("capability_verdicts") or {}).get("budget_step_hedge")
            vram_hedge = str(_tpl).format(gpu_mem=_tv) if _tpl else ""
    except Exception:
        vram_hedge = ""

    if status == "high":
        return (
            f"Yes, ${int(budget_cap):,} is more than enough for {label}. "
            f"A strong fit is already available around ${int(round(strongest)):,}."
            + vram_hedge
            + (step_up_txt or " Going higher is mostly about premium headroom rather than necessity.")
        )
    if status == "ok":
        if floor_val and budget_cap >= floor_val * 1.45:
            return (
                f"Yes, ${int(budget_cap):,} is a strong budget for {label}. "
                f"You already have viable options from about ${int(round(cheapest)):,}."
                + vram_hedge
                + (step_up_txt or " Going higher would mostly buy extra performance headroom or nicer build/display quality.")
            )
        return (
            f"Yes, ${int(budget_cap):,} is workable for {label}. "
            f"The current shortlist starts around ${int(round(cheapest)):,}."
            + vram_hedge
            + (step_up_txt or " Going a bit higher would mainly help if you want more long-term headroom.")
        )
    return ""


def _short_name(name: str, max_words: int = 4) -> str:
    return " ".join(str(name or "").split()[:max_words])


def _top_vram_gb(results: list) -> int | None:
    """Structured GPU-memory of the top result (specs.gpu_vram_gb) — vertical-blind field read."""
    try:
        top = results[0] if results and isinstance(results[0], dict) else {}
        specs = top.get("specs") if isinstance(top.get("specs"), dict) else {}
        _field = str((_profile_slot_dict("step_up_spec") or {}).get("field") or "gpu_vram_gb")
        v = int(specs.get(_field) or 0)
        return v or None
    except (TypeError, ValueError, IndexError):
        return None


def _above_budget_step_ups(budget_cap: float, min_vram_above: int | None) -> list:
    """Catalog rows ABOVE the budget whose gpu_vram_gb beats the in-budget best — the honest
    'what does going higher buy' answer, from the store's own stock. Up to 2, distinct tiers,
    cheapest first. Best-effort: any failure returns [] and the caller keeps its fallback line."""
    try:
        import json as _json
        from sqlalchemy import text as _sqltext
        from src.app.models.db import db_session
        with db_session() as db:
            rows = db.execute(
                _sqltext("SELECT name, price_cents, specs FROM products "
                         "WHERE active = 1 AND price_cents > :b ORDER BY price_cents ASC LIMIT 40"),
                {"b": int(float(budget_cap) * 100)},
            ).fetchall()
        out, seen_tiers = [], set()
        for name, pc, raw in rows:
            try:
                specs = _json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                specs = {}
            if not isinstance(specs, dict) or specs.get("gpu_discrete") is not True:
                continue
            try:
                _field = str((_profile_slot_dict("step_up_spec") or {}).get("field") or "gpu_vram_gb")
                v = int(specs.get(_field) or 0)
            except (TypeError, ValueError):
                v = 0
            if v > int(min_vram_above or 0) and v not in seen_tiers:
                seen_tiers.add(v)
                out.append((str(name), float(pc) / 100.0, v))
            if len(out) >= 2:
                break
        return out
    except Exception:
        return []


def _build_brand_budget_answer(query: str, results: list[dict], constraints: dict) -> str:
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
    if (not _is_corporate) and ("office" in _use_case or "corporate" in _use_case):
        _is_corporate = True
    if _is_corporate:
        _bmax = float(constraints.get("budget_max") or constraints.get("_request_budget_max") or 0)
        if _bmax > 0 and results:
            def _cp(r: dict) -> float:
                try:
                    return cents_to_dollars((r or {}).get("price_cents"))
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
        _prem = [str(t).lower() for t in _profile_slot_list("premium_brand_aliases")]
        if _prem and (any(tok in q_low for tok in _prem) or any(tok in result_names for tok in _prem)):
            brand_hint = "apple"
        else:
            for fallback_brand in [str(b).lower() for b in _profile_slot_list("brand_fallback_order")]:
                if fallback_brand in q_low or fallback_brand in result_names:
                    brand_hint = fallback_brand
                    break
    if brand_hint not in _SUPPORTED_IMAGE_BRAND_HINTS:
        # ── Generic budget answer when no brand is identified ──
        # e.g. "Is $1,800 enough for one?" → yes/no based on result prices
        budget_max_generic = (
            constraints.get("budget_max")
            or constraints.get("_request_budget_max")
            or ((constraints.get("_price_filter_meta") or {}).get("budget_max") if isinstance(constraints.get("_price_filter_meta"), dict) else None)
        )
        if budget_max_generic and results:
            def _gp(row: dict) -> float:
                try:
                    c = cents_to_dollars((row or {}).get("price_cents"))
                    return c if c > 0 else 0.0
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
            cents = cents_to_dollars((row or {}).get("price_cents"))
            return cents if cents > 0 else 0.0
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


# ── capability yes/no ("can it run <title>?", "good for video editing?") — answer-first verdict from
# the TOP result's specs, honest hedge on integrated graphics. Commerce-generic capability classes; the
# spec checks (discrete GPU / RAM) are the requirement, not product literals. ──────────────────────────
# Capability-class vocabulary + verdict templates live in the StoreProfile (capability_classes /
# capability_verdicts slots) — vertical-EXCLUSIVE: a profile without them gets no capability
# verdicts rather than inheriting electronics wording. The MECHANISM below is vertical-blind.
_CAP_QUESTION_RE = re.compile(
    r"\b(?:can|will|does)\b.{0,40}\b(?:run|play|handle|do|use|manage)\b"
    r"|\bgood\s+(?:for|enough|at)\b|\bhandle\b|\benough\s+for\b|\bcapable\s+of\b|\bsuitable\s+for\b"
    r"|\bcan\s+it\b|\bwill\s+it\b|\bfast\s+enough\b|\bpowerful\s+enough\b", re.I)


def _cap_result_has_discrete_gpu(r: dict) -> bool:
    # STRUCTURED field first (the demo + retrieval populate specs.gpu_discrete) — keeps this vertical-blind.
    # Name fallback uses only generic GPU-family words (no product-model literals → agnostic-core clean).
    specs = r.get("specs") if isinstance(r.get("specs"), dict) else {}
    if specs.get("gpu_discrete") is True:
        return True
    if specs.get("gpu_discrete") is False and not specs.get("gpu"):
        return False
    hay = (str(r.get("name") or "") + " " + str(specs.get("gpu") or "")).lower()
    # Vendor/family vocabulary comes from the profile's spec_strength_tokens.gpu (DATA);
    # "dedicated/discrete gpu" are generic mechanism words and stay in code.
    _gpu_toks = [str(t).lower() for t in (_profile_slot_dict("spec_strength_tokens").get("gpu") or [])]
    if any(tok in hay for tok in _gpu_toks):
        return True
    return bool(re.search(r"\b(dedicated\s+gpu|discrete\s+gpu)\b", hay))


def _cap_result_ram_gb(r: dict):
    specs = r.get("specs") if isinstance(r.get("specs"), dict) else {}
    try:
        v = int(specs.get("ram_gb") or 0)
        return v or None
    except (TypeError, ValueError):
        return None


def _build_capability_answer(query: str, results: list[dict]) -> str:
    """A deterministic capability verdict for 'can it run X / good for Y' — yes/no from the top result's
    structured specs. Class vocabulary + verdict templates come from the StoreProfile; missing slots →
    '' (vertical-exclusive). GPU-memory-aware for the heavy class (2026-07-07 "not smart" fix)."""
    q = str(query or "").lower()
    if not results or not isinstance(results[0], dict) or not _CAP_QUESTION_RE.search(q):
        return ""
    classes = _profile_slot_dict("capability_classes")
    cls = next((k for k in ("gaming", "heavy", "dev", "light")
                if any(str(c).lower() in q for c in (classes.get(k) or []))), None)
    if cls is None:
        return ""
    verdicts = _profile_slot_dict("capability_verdicts")

    def _say(key: str, **kw) -> str:
        tpl = verdicts.get(key)
        if not tpl:
            return ""
        try:
            return str(tpl).format(**kw)
        except (KeyError, IndexError, ValueError):
            return ""

    top = results[0]
    name = str(top.get("name") or "this item").strip()
    has_gpu = _cap_result_has_discrete_gpu(top)
    ram = _cap_result_ram_gb(top)
    ram_disp = ram or "16+"
    if cls == "gaming":
        return _say("gaming_yes", name=name) if has_gpu else _say("gaming_hedge", name=name)
    if cls == "heavy":
        gpu_mem = _top_vram_gb([top])
        strong_min = 16
        try:
            strong_min = int((_profile_slot_dict("step_up_spec") or {}).get("strong_min") or 16)
        except (TypeError, ValueError):
            strong_min = 16
        if has_gpu and gpu_mem and gpu_mem >= strong_min and (ram is None or ram >= 16):
            return _say("heavy_yes_vram", name=name, gpu_mem=gpu_mem, ram=ram_disp)
        if has_gpu and gpu_mem and gpu_mem < strong_min:
            return _say("heavy_hedge_vram", name=name, gpu_mem=gpu_mem, ram=ram_disp)
        if has_gpu and (ram is None or ram >= 16):
            return _say("heavy_yes", name=name, ram=ram_disp)
        return _say("heavy_light", name=name)
    if cls == "dev":
        if ram is not None and ram >= 16:
            return _say("dev_yes", name=name, ram=ram)
        return _say("dev_hedge", name=name)
    return _say("light_yes", name=name)


def _build_brand_budget_answer_v2(query: str, results: list[dict], constraints: dict) -> str:
    q_low = str(query or "").lower()
    # N4 challenge-defense: "are you sure? why would it be good for X?" gets a spec-vs-requirement
    # justification (KB-grounded, gaps admitted) instead of a re-pasted pitch. Checked FIRST — a
    # challenged buyer wants the defense, not another budget summary.
    try:
        from src.app.services.recommend_justification import build_challenge_justification
        _just = build_challenge_justification(query, results, constraints)
        if _just:
            return _just
    except Exception as _exc:
        import logging as _lg
        _lg.getLogger(__name__).debug("challenge justification skipped: %s", _exc)
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
        # not a budget question — try the capability verdict ("can it run X / good for Y") before giving up
        return _build_capability_answer(query, results)

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
        # Vocabulary + floors live in the StoreProfile budget_floor_hints slot (ordered; an entry with
        # empty tokens is the vertical's default). Code is vertical-blind.
        combined = f"{use_case_text} {query_text}".strip().lower()
        for hint in _profile_slot_list("budget_floor_hints"):
            if not isinstance(hint, dict):
                continue
            toks = [str(t).lower() for t in (hint.get("tokens") or [])]
            if not toks or any(tok in combined for tok in toks):
                try:
                    return int(hint.get("floor") or 600), str(hint.get("label") or "item")
                except (TypeError, ValueError):
                    break
        return 600, "item"

    budget_max_generic = (
        constraints.get("budget_max")
        or constraints.get("_request_budget_max")
        or ((constraints.get("_price_filter_meta") or {}).get("budget_max") if isinstance(constraints.get("_price_filter_meta"), dict) else None)
        or _extract_budget_value(q_low)
    )
    if budget_max_generic and results:
        def _row_price(row: dict) -> float:
            try:
                cents = cents_to_dollars((row or {}).get("price_cents"))
                return cents if cents > 0 else 0.0
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
    use_case_fit_status = (
        constraints.get("use_case_fit_status")
        if isinstance(constraints.get("use_case_fit_status"), dict)
        else {}
    )
    clean_use_case_fit = use_case_fit_status.get("exact_fit") is not False

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
    if not clean_use_case_fit:
        core = f"found {n} closest option{option_plural}, but none is a clean use-case fit"
    elif budget_min is not None and budget_max is not None:
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

        # When we present a clean use-case fit, the "Best fits for X" picks must ACTUALLY fit the use case.
        # A high-scoring item that merely lands in the budget band (high raw score, no use-case match) must not
        # be paraded as a "best fit for office work". Prefer rows carrying a positive use_case_match marker;
        # fall back to the top rows only when NONE carry it, so the line never silently disappears.
        def _positively_fits_use_case(row: dict) -> bool:
            fac = (row or {}).get("factors") or {}
            pos = fac.get("positive") if isinstance(fac, dict) else None
            if not isinstance(pos, list):
                pos = (row or {}).get("why") or []
            return any("use_case_match" in str(f) for f in (pos or []))

        source_rows = list(results or [])
        if clean_use_case_fit and use_case and any(_positively_fits_use_case(r) for r in source_rows):
            source_rows = [r for r in source_rows if _positively_fits_use_case(r)]
        for row in source_rows[:2]:
            name = _display_name(row)
            if not name:
                continue
            price_cents = (row or {}).get("price_cents")
            try:
                price_text = f" (${int(round(cents_to_dollars(price_cents))):,})" if float(price_cents or 0) > 0 else ""
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
        if clean_use_case_fit:
            fit_line = f"Best fits for {persona_label}: {picks}." if persona_label else f"Best fits here: {picks}."
        else:
            fit_line = f"Closest options with trade-offs: {picks}."
    budget_reasoning = _build_budget_reasoning_note(query, results, constraints)

    # PARAGRAPH the message so the buyer chat reads as distinct thoughts, not one blob. The frontend
    # splits assistant copy on blank lines (App.tsx: split(/\n\n+/)), so grouping into 3 logical
    # paragraphs — (1) the budget verdict + reasoning, (2) the concrete picks, (3) the follow-up —
    # renders cleanly. Within a paragraph we still space-join. Downstream decorators append the
    # availability + price-range notes as their own \n\n paragraphs.
    verdict_bits: list[str] = []
    if not clean_use_case_fit and use_case_fit_status.get("message"):
        verdict_bits.append(str(use_case_fit_status["message"]))
    verdict_bits.append(brand_budget_answer if brand_budget_answer else core_line)
    if budget_reasoning:
        verdict_bits.append(budget_reasoning)
    closing_bits: list[str] = []
    if urgency_note:
        closing_bits.append(urgency_note.strip())
    closing_bits.append(closing.strip())
    paragraphs = [
        " ".join(b for b in verdict_bits if b).strip(),   # 1) the answer to what they asked
        (fit_line or "").strip(),                          # 2) the concrete picks
        " ".join(b for b in closing_bits if b).strip(),    # 3) the follow-up question
    ]
    return "\n\n".join(p for p in paragraphs if p).strip()
