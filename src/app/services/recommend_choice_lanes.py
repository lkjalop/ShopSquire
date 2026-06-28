"""Backend-driven recommendation CHOICE LANES (agnostic CORE).

Demarcates the ranked candidates into operator-meaningful lanes (the lane SET is defined entirely by the
active StoreProfile — e.g. a business line, a vendor-ecosystem line, a budget line, and a non-primary
"specialty chassis" line) so the storefront groups options on BACKEND evidence instead of frontend
keyword guessing. The lane DEFINITIONS
(markers / exclusions / explanation / metrics / priority / primary_for) are DATA from the active StoreProfile
slot ``recommendation_lanes`` — this module only does opaque text-matching + grouping, so it stays
vertical-blind. Emits ``right_panel.device_lanes``.

A candidate joins the highest-priority lane whose any marker matches its (name + specs + features) haystack
AND none of whose exclusions match. ``primary`` reflects the query's use-case (a lane is primary when the
resolved use_case is in its ``primary_for``, and never for a lane flagged ``non_primary``) — so a work query
never presents a gaming chassis as a primary pick. Never raises; returns [] when the profile defines no lanes
(the caller then falls back to its own heuristic).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional


def _haystack(p: Dict[str, Any]) -> str:
    name = str(p.get("name") or "")
    try:
        specs = json.dumps(p.get("specs") or {}, ensure_ascii=False)
    except Exception:
        specs = ""
    feats = " ".join(str(x) for x in (p.get("features") or []))
    return f"{name} {specs} {feats}".lower()


def _price(p: Dict[str, Any]) -> Optional[float]:
    for k in ("price", "price_cents"):
        v = p.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v) / 100.0 if k == "price_cents" else float(v)
    return None


def _matches(haystack: str, markers: List[Any]) -> bool:
    return any(str(m).strip().lower() in haystack for m in (markers or []) if str(m).strip())


def assign_device_lanes(
    products: List[Dict[str, Any]],
    *,
    profile_fn: Callable,
    use_case: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Group ``products`` into the profile's recommendation_lanes. Returns an ordered list of non-empty
    lane dicts: {key, title, explanation, metrics, primary, non_primary, count, price_min, price_max,
    skus, products[]}. Empty list when the profile defines no lanes (caller falls back to its heuristic)."""
    try:
        lanes_cfg = profile_fn("recommendation_lanes", profile_id=profile_id, default=[]) if profile_fn else []
    except Exception:
        lanes_cfg = []
    if not isinstance(lanes_cfg, list) or not lanes_cfg or not products:
        return []

    lanes = sorted(
        [l for l in lanes_cfg if isinstance(l, dict) and l.get("key")],
        key=lambda l: int(l.get("priority") or 100),
    )
    uc = str(use_case or "").strip().lower()
    buckets: Dict[str, List[Dict[str, Any]]] = {str(l["key"]): [] for l in lanes}
    other: List[Dict[str, Any]] = []

    for p in products:
        if not isinstance(p, dict):
            continue
        hay = _haystack(p)
        placed = False
        for lane in lanes:
            if _matches(hay, lane.get("exclusions")):
                continue
            if _matches(hay, lane.get("markers")):
                buckets[str(lane["key"])].append(p)
                placed = True
                break
        if not placed:
            other.append(p)

    def _summ(p: Dict[str, Any]) -> Dict[str, Any]:
        return {"sku": str(p.get("sku") or ""), "name": str(p.get("name") or ""),
                "price": _price(p), "why": [str(x) for x in (p.get("why") or [])[:2]]}

    out: List[Dict[str, Any]] = []
    for lane in lanes:
        items = buckets[str(lane["key"])]
        if not items:
            continue
        prices = [v for v in (_price(p) for p in items) if v is not None]
        primary_for = [str(x).strip().lower() for x in (lane.get("primary_for") or [])]
        # A "specialty" lane (e.g. discrete-GPU / gaming chassis) is PRIMARY for the use-cases it's built
        # for — gaming AND GPU-heavy work like AI/ML, content/video, 3D/CAD — and is demoted to non-primary
        # ONLY when the query is something it doesn't serve (normal office work). So GPU laptops lead a
        # creative/AI query but never a corporate-fleet one. `non_primary: true` is kept as back-compat for
        # "always specialty". Non-specialty lanes are never force-demoted.
        specialty = bool(lane.get("specialty") or lane.get("non_primary"))
        is_primary = bool(uc and uc in primary_for)
        is_non_primary = bool(specialty and not is_primary)
        out.append({
            "key": str(lane["key"]),
            "title": str(lane.get("title") or lane["key"]),
            "explanation": str(lane.get("explain") or ""),
            "metrics": [str(m) for m in (lane.get("metrics") or [])],
            "primary": is_primary,
            "non_primary": is_non_primary,
            "count": len(items),
            "price_min": min(prices) if prices else None,
            "price_max": max(prices) if prices else None,
            "skus": [str(p.get("sku") or "") for p in items],
            "products": [_summ(p) for p in items[:6]],
        })
    if other:
        prices = [v for v in (_price(p) for p in other) if v is not None]
        out.append({
            "key": "other", "title": "Other options", "explanation": "Other candidates that did not match a named lane.",
            "metrics": [], "primary": False, "non_primary": True, "count": len(other),
            "price_min": min(prices) if prices else None, "price_max": max(prices) if prices else None,
            "skus": [str(p.get("sku") or "") for p in other], "products": [_summ(p) for p in other[:6]],
        })
    # primary lanes first (most relevant to the query), then by the configured priority order already baked in
    out.sort(key=lambda l: (0 if l["primary"] else (2 if l["non_primary"] else 1)))
    return out


def fleet_advisory(lanes: List[Dict[str, Any]], *, use_case: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Procurement-truth signal for a use-case with a primary expectation (e.g. a work/office query). If the
    results carry NO primary-fit lane with products but DO carry a non-primary lane (e.g. only gaming
    chassis), advise sourcing/procurement instead of presenting the specialty options as the answer.
    Returns None when coverage is fine or there is no use-case context. Vertical-blind (reads only the
    primary/non_primary/count flags the lanes already carry)."""
    if not use_case or not lanes:
        return None
    primary = [l for l in lanes if l.get("primary") and l.get("count")]
    non_primary = [l for l in lanes if l.get("non_primary") and l.get("count")]
    if not primary and non_primary:
        return {
            "coverage": "none",
            "message": ("No primary-fit options for this use-case in the current results. Recommend "
                        "sourcing/procurement of suitable units rather than presenting the specialty "
                        "options shown as primary picks."),
            "non_primary_lanes": [str(l.get("key")) for l in non_primary],
            "suggest_procurement": True,
        }
    if primary and non_primary:
        return {"coverage": "partial",
                "message": "Primary-fit options found; specialty options are listed separately and are "
                           "not recommended as primary picks.",
                "suggest_procurement": False}
    return None
