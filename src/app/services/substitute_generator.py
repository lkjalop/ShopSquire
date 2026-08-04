"""Substitute / alternative generator (agnostic CORE).

When the buyer's exact pick can't be fully fulfilled (out of budget, short on stock, OOS), the buyer wants
REAL alternatives — the nearest catalog items by the attributes that matter. options.py can rank a
substitute but never finds one; this module finds + ranks them.

Vertical-blind by construction: the candidate pool is "same category" (an opaque DATA column), and the
attributes that define "near" come from the active StoreProfile's narration_spec_dimensions — never
hardcoded here. So it substitutes laptops by GPU/RAM, chairs by material/load-rating, or shirts by
size/colour with zero code change. Reads only; never raises.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

DEFAULT_TENANT = "default"


def _parse_specs(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def _comparable_keys(profile_fn) -> List[str]:
    """The attribute keys that define 'near', from the profile's narration_spec_dimensions (first variant
    key per dimension). Empty when the profile lacks the slot — then we rank on price/stock only."""
    try:
        dims = profile_fn("narration_spec_dimensions", default=None) if profile_fn else None
    except Exception:
        dims = None
    keys: List[str] = []
    for d in (dims or []):
        if not isinstance(d, dict):
            continue
        for v in (d.get("variants") or []):
            if isinstance(v, dict) and v.get("key"):
                keys.append(str(v["key"]))
                break
    return keys


def _attr_match(seed: Dict[str, Any], cand: Dict[str, Any], keys: List[str]) -> int:
    """How many comparable attributes the candidate meets-or-beats the seed on. Numeric: cand >= 0.9*seed
    (equal-or-better, within 10%); string: case-insensitive equal. Agnostic — no key is special."""
    score = 0
    for k in keys:
        sv, cv = seed.get(k), cand.get(k)
        if sv is None or cv is None:
            continue
        try:
            if float(sv) > 0 and float(cv) >= float(sv) * 0.9:
                score += 1
                continue
        except (TypeError, ValueError):
            if str(sv).strip().lower() == str(cv).strip().lower():
                score += 1
    return score


def find_substitutes(db, sku: str, *, use_case: Optional[str] = None, specs: Optional[List[str]] = None,
                     budget_min: Optional[float] = None, budget_max: Optional[float] = None,
                     exclude_brands: Optional[List[str]] = None, limit: int = 5,
                     tenant_id: str = DEFAULT_TENANT, profile_fn=None) -> List[Dict[str, Any]]:
    """Ranked substitutes for ``sku``: same category, in-budget, nearest by profile attributes, seed +
    excluded brands removed. Returns [{sku, name, price_cents, brand, spec_match, spec_total,
    price_delta_cents, tradeoff}]. Empty on any failure or no catalog row. Budgets in DOLLARS."""
    if db is None or not sku:
        return []
    if profile_fn is None:
        try:
            from src.app.platform.store_profile import profile_slot as profile_fn  # type: ignore
        except Exception:
            profile_fn = None
    try:
        from sqlalchemy import text
        seed = db.execute(text("SELECT name, price_cents, specs, category, brand FROM products "
                               "WHERE sku=:s AND COALESCE(active,1)=1 LIMIT 1"), {"s": str(sku)}).fetchone()
        if not seed:
            return []
        seed_price = int(seed[1] or 0)
        seed_specs = _parse_specs(seed[2])
        category = str(seed[3] or seed_specs.get("category") or "").strip()
        if not category:
            return []
        rows = db.execute(text(
            "SELECT sku, name, price_cents, specs, brand FROM products "
            "WHERE COALESCE(active,1)=1 AND category=:c AND sku<>:s"),
            {"c": category, "s": str(sku)}).fetchall()
    except Exception:
        return []

    keys = _comparable_keys(profile_fn)
    excl = {str(b).strip().lower() for b in (exclude_brands or []) if str(b).strip()}
    bmax_cents = float(budget_max) * 100.0 if budget_max is not None else None
    bmin_cents = float(budget_min) * 100.0 if budget_min is not None else None
    out: List[Dict[str, Any]] = []
    for r in rows:
        c_sku, c_name, c_price, c_specs_raw, c_brand = str(r[0]), str(r[1] or ""), int(r[2] or 0), r[3], r[4]
        if c_brand and str(c_brand).strip().lower() in excl:
            continue
        if bmax_cents is not None and c_price > bmax_cents * 1.10:   # allow a 10% stretch, no further
            continue
        if bmin_cents is not None and c_price < bmin_cents * 0.60:   # far below tier → not a real sub
            continue
        c_specs = _parse_specs(c_specs_raw)
        match = _attr_match(seed_specs, c_specs, keys)
        delta = c_price - seed_price
        out.append({
            "sku": c_sku, "name": c_name, "price_cents": c_price, "brand": (str(c_brand) if c_brand else None),
            "spec_match": match, "spec_total": len(keys), "price_delta_cents": delta,
            "tradeoff": _tradeoff(c_name, delta, match, len(keys)),
            # sort key (not returned): more matches, then closer price, then cheaper
            "_rank": (match, -abs(delta), -c_price),
        })
    out.sort(key=lambda x: x["_rank"], reverse=True)
    for x in out:
        x.pop("_rank", None)
    return out[: max(1, int(limit))]


def _tradeoff(name: str, delta_cents: int, match: int, total: int) -> str:
    if delta_cents > 0:
        price_txt = f"${delta_cents/100:,.0f} more"
    elif delta_cents < 0:
        price_txt = f"${abs(delta_cents)/100:,.0f} less"
    else:
        price_txt = "same price"
    spec_txt = f"{match}/{total} key specs meet or beat your pick" if total else "comparable"
    return f"{price_txt}; {spec_txt}"
