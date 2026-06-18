"""Shared recommend leaf utilities — the foundation for the core/adapter stage split.

These are the small, PURE helpers (no DB, no request locals, no closures) that more than one
extracted stage needs. Pulling them here breaks the circular-import knot: a stage service
(budget advisor, narration, fast-path …) can import these without importing the router, and the
router re-exports them so its own call-sites stay unchanged.

CORE mechanism: brand-token matching, brand display, price normalisation.
ADAPTER (flavour): the brand alias / display maps below are still inline electronics flavour
(thinkpad/legion/alienware …). They are the Phase-2 profile-back target (a non-electronics
vertical supplies its own aliases via the StoreProfile `manufacturers` map) — which is why this
module is intentionally NOT yet on the no-flavour-in-core lint list, exactly like
recommend_image_hints.py. Tracked, not hidden.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _candidate_matches_brand(candidate: Dict[str, Any] | None, brands: List[str] | None) -> bool:
    c = candidate or {}
    req = [str(b or "").strip().lower() for b in (brands or []) if str(b or "").strip()]
    if not req:
        return False
    name = str(c.get("name") or "").lower()
    sku = str(c.get("sku") or "").lower()
    text_blob = f"{name} {sku}"
    alias = {
        "apple": ["apple", "macbook", "imac"],
        "microsoft": ["microsoft", "surface"],
        "asus": ["asus", "vivobook", "zenbook", "rog", "tuf"],
        "lenovo": ["lenovo", "ideapad", "thinkpad", "yoga", "legion"],
        "hp": ["hp", "envy", "victus", "omen", "omnibook", "elitebook", "probook"],
        "dell": ["dell", "inspiron", "xps", "latitude", "vostro"],
        "msi": ["msi", "stealth", "raider", "titan"],
        "alienware": ["alienware"],
        "acer": ["acer", "swift", "aspire", "predator", "nitro"],
        "samsung": ["samsung", "galaxy book"],
        "razer": ["razer", "blade"],
        "gigabyte": ["gigabyte", "aorus"],
        "toshiba": ["toshiba", "dynabook"],
    }
    for b in req:
        probes = alias.get(b, [b])
        if any(p in text_blob for p in probes):
            return True
    return False


def _brand_display_name(brand: str | None) -> str:
    key = str(brand or "").strip().lower()
    return {
        "apple": "Apple",
        "asus": "ASUS",
        "lenovo": "Lenovo",
        "hp": "HP",
        "dell": "Dell",
        "msi": "MSI",
        "alienware": "Alienware",
        "microsoft": "Microsoft Surface",
        "acer": "Acer",
        "samsung": "Samsung",
        "razer": "Razer",
        "gigabyte": "Gigabyte",
        "toshiba": "Toshiba",
        "windows": "Windows",
    }.get(key, key.capitalize() if key else "")


def _result_price_dollars(row: Dict[str, Any] | None) -> float | None:
    r = row or {}
    try:
        if isinstance(r.get("price"), (int, float)):
            p = float(r.get("price"))
            if p > 0:
                return p
    except Exception:
        pass
    try:
        if isinstance(r.get("price_cents"), (int, float)):
            pc = float(r.get("price_cents"))
            if pc > 0:
                return round(pc / 100.0, 2)
    except Exception:
        pass
    return None
