"""Budget parsing, bracket classification, and price bucketing.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
CORE (vertical-agnostic):
  • BUDGET_BRACKETS — price thresholds. Currently hardcoded at $500/$900/$1500
    which happen to be laptop-centric. Phase 2: read from StoreProfile["price_bands_usd"].
  • classify_budget_bracket() — generic threshold lookup.
  • is_budget_shopping_query() — regex budget detection. The patterns ("under",
    "between", "$X") are vertical-agnostic.
  • extract_explicit_budget_override() — regex budget extraction. Vertical-agnostic.
  • build_price_buckets() — sorts results into within/above/below budget. Vertical-agnostic.

ADAPTER (product-type-specific):
  • capability_preface() — checks GPU/RAM against use_case_kb.json. The GPU token
    lists ("rtx", "geforce", "nvidia", "radeon") are electronics-specific.
    Phase 2: generalize to profile-driven capability checks.
  • load_capability_kb() — loads config/use_case_kb.json (electronics-focused).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from src.app.services.recommend_utils import _result_price_dollars


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Budget bracket classification and parsing (vertical-agnostic).
# Phase 2: read thresholds from StoreProfile["price_bands_usd"].
# ═══════════════════════════════════════════════════════════════════════════════

BUDGET_BRACKETS = [
    (500,   "entry"),
    (900,   "mid"),
    (1500,  "high"),
    (float("inf"), "ultra"),
]


def classify_budget_bracket(budget_max: float | int | None) -> str | None:
    """Map a numeric budget_max to a bracket label: entry / mid / high / ultra."""
    if budget_max is None:
        return None
    try:
        bmax = float(budget_max)
    except (TypeError, ValueError):
        return None
    for threshold, label in BUDGET_BRACKETS:
        if bmax <= threshold:
            return label
    return "ultra"


def is_budget_shopping_query(query: str | None) -> bool:
    q_low = str(query or "").strip().lower()
    if not q_low:
        return False
    if any(
        tok in q_low
        for tok in (
            "budget",
            "price range",
            "under",
            "below",
            "up to",
            "between",
            "only have",
            "is that enough",
            "is this enough",
            "is $",
            "for school",
            "for high school",
            "for university",
            "for work",
            "for gaming",
        )
    ):
        return True
    return bool(
        re.search(r"\b\d{3,5}\s*(?:-|to|and)\s*\d{3,5}\b", q_low)
        or re.search(r"\$\s*\d{3,5}\b", q_low)
        or re.search(r"\b(?:for|around|about)\s+\d{3,5}\b", q_low)
    )


def extract_explicit_budget_override(query: str | None) -> Dict[str, Any]:
    q_low = str(query or "").strip().lower()
    if not q_low:
        return {}
    m_between = re.search(r"\bbetween\s*\$?([\d,]+)\s*(?:and|to|-)\s*\$?([\d,]+)\b", q_low)
    if m_between:
        lo = int(str(m_between.group(1)).replace(",", ""))
        hi = int(str(m_between.group(2)).replace(",", ""))
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi), "mode": "between"}
    m_range = re.search(
        r"(?:budget(?:\s+is|\s+of)?|price\s+range|range)?\s*\$?\s*([\d,]+)\s*(?:to|-)\s*\$?\s*([\d,]+)",
        q_low,
    )
    if m_range:
        lo = int(str(m_range.group(1)).replace(",", ""))
        hi = int(str(m_range.group(2)).replace(",", ""))
        if lo != hi and max(lo, hi) <= 100_000:
            return {"budget_min": min(lo, hi), "budget_max": max(lo, hi), "mode": "range"}
    m_under = re.search(r"\b(?:under|below|max(?:imum)?|up to|only have|have|budget(?:\s+is|\s+of)?|for)\s+\$?\s*(\d[\d,]+)\b", q_low)
    if m_under and ("enough" in q_low or any(tok in q_low for tok in ("under", "below", "up to", "only have", "budget"))):
        cap = int(str(m_under.group(1)).replace(",", ""))
        return {"budget_min": None, "budget_max": cap, "mode": "cap"}
    m_enough = re.search(r"\b(?:is|will)\s+\$?\s*(\d[\d,]+)\s+enough\b", q_low)
    if m_enough:
        cap = int(str(m_enough.group(1)).replace(",", ""))
        return {"budget_min": None, "budget_max": cap, "mode": "cap"}
    m_over = re.search(r"\b(?:over|above|min(?:imum)?|at least)\s+\$?\s*(\d[\d,]+)\b", q_low)
    if m_over:
        floor = int(str(m_over.group(1)).replace(",", ""))
        return {"budget_min": floor, "budget_max": None, "mode": "floor"}
    return {}


def build_price_buckets(
    *,
    results: List[Dict[str, Any]] | None,
    constraints: Dict[str, Any] | None,
    cap: int = 4,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build explicit UI-friendly price buckets for recommendation alternatives."""
    out: Dict[str, List[Any]] = {
        "within_budget": [],
        "closest_above_budget": [],
        "closest_below_budget": [],
    }
    rows = [r for r in (results or []) if isinstance(r, dict)]
    if not rows:
        return out

    c = constraints or {}
    bmin = c.get("budget_min")
    bmax = c.get("budget_max")
    try:
        bmin = int(bmin) if bmin is not None else None
    except Exception:
        bmin = None
    try:
        bmax = int(bmax) if bmax is not None else None
    except Exception:
        bmax = None

    priced: List[tuple[Dict[str, Any], float]] = []
    for r in rows:
        p = _result_price_dollars(r)
        if p is None:
            continue
        priced.append((r, p))

    if not priced:
        return out

    within: List[Dict[str, Any]] = []
    above: List[tuple[Dict[str, Any], float]] = []
    below: List[tuple[Dict[str, Any], float]] = []

    for r, p in priced:
        if bmin is not None and bmax is not None:
            if bmin <= p <= bmax:
                within.append(r)
            elif p > bmax:
                above.append((r, p - float(bmax)))
            elif p < bmin:
                below.append((r, float(bmin) - p))
            continue
        if bmax is not None:
            if p <= bmax:
                within.append(r)
            else:
                above.append((r, p - float(bmax)))
            continue
        if bmin is not None:
            if p >= bmin:
                within.append(r)
            else:
                below.append((r, float(bmin) - p))
            continue
        within.append(r)

    above_sorted = [r for r, _ in sorted(above, key=lambda x: x[1])]
    below_sorted = [r for r, _ in sorted(below, key=lambda x: x[1])]

    out["within_budget"] = within[:cap]
    out["closest_above_budget"] = above_sorted[:cap]
    out["closest_below_budget"] = below_sorted[:cap]
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER — Electronics-specific capability preface.
# Checks GPU/RAM against use_case_kb.json required_specs. The GPU token lists
# ("rtx", "geforce", "nvidia", "radeon") are electronics-specific.
# Phase 2: generalize to profile-driven capability checks.
# ═══════════════════════════════════════════════════════════════════════════════

_CAPABILITY_KB_CACHE: dict | None = None
_CAPABILITY_KB_LOADED: bool = False


def load_capability_kb() -> dict:
    global _CAPABILITY_KB_CACHE, _CAPABILITY_KB_LOADED
    if _CAPABILITY_KB_LOADED:
        return _CAPABILITY_KB_CACHE or {}
    try:
        import json as _json
        _kb_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "use_case_kb.json")
        )
        with open(_kb_path, "r", encoding="utf-8") as _f:
            _CAPABILITY_KB_CACHE = _json.load(_f)
    except Exception:
        _CAPABILITY_KB_CACHE = {}
    _CAPABILITY_KB_LOADED = True
    return _CAPABILITY_KB_CACHE or {}


def capability_preface(query: str, results: list[dict], constraints: dict) -> str:
    if not results:
        return ""
    q_low = str(query or "").lower()
    _cap_patterns = (
        "can this run", "can it run", "will this run", "will it run",
        "can this handle", "can it handle", "will this handle", "will it handle",
        "can i play", "can i run", "can this play", "can you run",
        "will this work for", "suitable for", "meant for", "compatible with",
    )
    if not any(tok in q_low for tok in _cap_patterns):
        return ""
    try:
        _kb = load_capability_kb()
    except Exception:
        return ""
    aliases: dict = _kb.get("use_case_aliases") or {}
    use_cases: dict = _kb.get("use_cases") or {}
    detected_uc = str(constraints.get("use_case") or "").lower().strip()
    if not detected_uc:
        for _alias, _uc in aliases.items():
            if _alias.lower() in q_low:
                detected_uc = _uc
                break
    if not detected_uc:
        return ""
    kb_entry: dict = use_cases.get(detected_uc) or {}
    if not kb_entry:
        return ""
    req: dict = kb_entry.get("required_specs") or {}
    excl: list = kb_entry.get("exclusion_rules") or []
    label: str = kb_entry.get("label") or detected_uc.replace("_", " ").title()
    top = results[0] if results else {}
    specs: dict = top.get("specs") if isinstance(top.get("specs"), dict) else {}
    full_text = f"{(top.get('name') or '').lower()} {str(specs).lower()}"
    _discrete_markers = ("rtx", "geforce", "nvidia", "radeon rx", "radeon 6", "radeon 7",
                          "radeon 8", "arc a", "discrete")
    has_discrete = any(k in full_text for k in _discrete_markers)
    violations: list[str] = []
    if "integrated_gpu_only" in excl and not has_discrete:
        violations.append("lacks a dedicated GPU")
    if "fanless_design" in excl and "fanless" in full_text:
        violations.append("fanless design limits sustained performance")
    unmet: list[str] = []
    if req.get("gpu_tier") and "discrete" in str(req["gpu_tier"]) and not has_discrete:
        unmet.append("dedicated GPU")
    ram_req = req.get("ram_gb_min")
    if ram_req:
        try:
            ram_val = int(specs.get("ram_gb") or 0)
            if 0 < ram_val < int(ram_req):
                unmet.append(f"RAM ({ram_val}GB, needs {ram_req}GB+)")
        except Exception:
            pass
    top_name = str(top.get("name") or "The top result")
    if violations or unmet:
        missing = (violations + unmet)[0]
        return f"No — {top_name} isn't ideal for {label}: it {missing}."
    return f"Yes — {top_name} handles {label} tasks well."
