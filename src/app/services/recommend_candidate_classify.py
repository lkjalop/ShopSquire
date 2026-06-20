"""Candidate classification, brand SQL predicates, and GPU intent profiling.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
ALL ADAPTER (product-type-specific / electronics):
  • candidate_looks_like_laptop() — laptop-specific positive/negative term matching.
  • candidate_looks_like_device() — device vs accessory classification using
    electronics-specific SKU prefixes and product names.
  • brand_sql_predicate() — brand-to-SQL WHERE clause mapping for electronics brands.
    Phase 2: generalize to profile-driven brand → SKU/name patterns.
  • candidate_has_discrete_gpu() — GPU detection via electronics-specific markers.
  • gpu_intent_profile() — GPU task/intent detection via electronics-specific terms.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict

# GPU term constants (imported from recommend.py scope; re-declared here for
# self-containment since the originals are still in the monolith).
_GPU_TASK_TERMS = (
    "ai training",
    "model training",
    "machine learning",
    "deep learning",
    "cuda",
    "pytorch",
    "tensorflow",
    "vram",
    "video rendering",
    "rendering",
    "3d",
    "blender",
    "premiere",
    "davinci",
    "gaming",
    "esports",
    "rtx",
)

_GPU_WITH_TERMS = (
    "with gpu",
    "dedicated gpu",
    "discrete gpu",
    "rtx",
    "geforce",
    "radeon",
    "graphics card",
)

_GPU_WITHOUT_TERMS = (
    "without gpu",
    "no gpu",
    "integrated graphics only",
    "integrated gpu only",
    "no graphics card",
)


def candidate_looks_like_laptop(candidate: Dict[str, Any] | None) -> bool:
    c = candidate or {}
    name = str(c.get("name") or "").lower()
    negative_terms = (
        "monitor", "headphone", "headset", "earbud", "speaker",
        "keyboard", "mouse", "docking station", "webcam", "microphone", "sleeve",
    )
    if any(t in name for t in negative_terms):
        return False
    try:
        text_blob = f"{name} {json.dumps(c.get('specs') or {}, ensure_ascii=False)}".lower()
    except Exception:
        text_blob = name
    positive_terms = (
        "laptop", "notebook", "ultrabook", "macbook", "chromebook", "thinkpad",
        "ideapad", "legion", "yoga", "vivobook", "zenbook", "gram", "xps",
    )
    return any(t in text_blob for t in positive_terms)


def candidate_looks_like_device(candidate: Dict[str, Any] | None) -> bool:
    """Return True for primary devices, not accessories."""
    c = candidate or {}
    name = str(c.get("name") or "").lower()
    sku = str(c.get("sku") or "").upper()
    specs = c.get("specs") if isinstance(c.get("specs"), dict) else {}
    category = str(specs.get("category") or specs.get("product_category") or "").lower()
    if category in {"laptop", "notebook", "tablet", "desktop", "pc", "chromebook", "phone", "mobile"}:
        return True
    if category and category not in {"computer", "device"}:
        return False
    negative_terms = (
        "monitor", "headphone", "headset", "earbud", "speaker", "keyboard",
        "mouse", "dock", "docking station", "webcam", "microphone", "sleeve",
        "case", "bag", "charger", "cable", "ssd", "card reader", "stand",
        "power bank", "stylus", "audio interface",
    )
    if any(t in name for t in negative_terms):
        return False
    device_prefixes = ("LAP-", "SYN-LAP-", "TAB-", "PHO-", "MOB-", "GAM-", "RGAM-", "PC-", "NB-")
    if sku.startswith(device_prefixes):
        return True
    text_blob = f"{name} {json.dumps(specs, ensure_ascii=False)}".lower()
    positive_terms = (
        "laptop", "notebook", "ultrabook", "macbook", "chromebook", "thinkpad",
        "ideapad", "legion", "yoga", "vivobook", "zenbook", "gram", "xps",
        "victus", "omen", "alienware", "tablet", "ipad", "galaxy tab",
        "desktop", "all-in-one", "pc",
    )
    return any(t in text_blob for t in positive_terms)


@lru_cache(maxsize=8)
def _brand_sql_patterns_for(pid: str) -> Dict[str, str]:
    """brand-key -> SQL WHERE fragment, resolved from the active StoreProfile.

    TRUSTED CONFIG ONLY: these fragments are interpolated into SQL. No user input ever
    reaches them — the caller normalises `brand` to a key and looks up a fixed string.
    Electronics carries the verbatim predicates in its `brand_sql_patterns` slot; other
    verticals fall back to a name-LIKE predicate derived from their `manufacturers` slot.
    """
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("brand_sql_patterns", profile_id=pid, default=None)
    if isinstance(raw, dict) and raw:
        return {str(k).strip().lower(): str(v) for k, v in raw.items()}
    # Fallback: derive a name-LIKE predicate per brand from manufacturers (name+aliases+lines).
    mans = profile_slot("manufacturers", profile_id=pid, default=None) or {}
    out: Dict[str, str] = {}
    for name, spec in mans.items():
        tokens = [name] + list((spec or {}).get("aliases") or []) + list((spec or {}).get("lines") or [])
        seen: set[str] = set()
        likes: list[str] = []
        for t in tokens:
            tl = str(t).strip().lower()
            if tl and tl not in seen:
                seen.add(tl)
                likes.append("LOWER(p.name) LIKE '%" + tl.replace("'", "''") + "%'")
        if likes:
            out[str(name).strip().lower()] = "(" + " OR ".join(likes) + ")"
    return out


def reset_cache() -> None:
    """Clear the per-profile brand-SQL cache (test isolation / profile reload)."""
    try:
        _brand_sql_patterns_for.cache_clear()
    except Exception:
        pass


def brand_sql_predicate(brand: str | None) -> str:
    key = str(brand or "").strip().lower()
    from src.app.platform.store_profile import active_profile_id
    return _brand_sql_patterns_for(active_profile_id()).get(key, "")


def candidate_has_discrete_gpu(candidate: Dict[str, Any] | None) -> bool:
    c = candidate or {}
    try:
        text_blob = f"{c.get('name') or ''} {json.dumps(c.get('specs') or {}, ensure_ascii=False)}".lower()
    except Exception:
        text_blob = str(c).lower()
    dedicated_markers = ("rtx", "geforce", "radeon", "discrete", "graphics card", "dgpu")
    integrated_markers = ("integrated", "intel iris", "uhd graphics", "igpu")
    has_integrated = any(x in text_blob for x in integrated_markers)
    has_dedicated = any(x in text_blob for x in dedicated_markers)
    if has_dedicated:
        return True
    if has_integrated:
        return False
    return False


def gpu_intent_profile(query: str | None, constraints: Dict[str, Any] | None = None) -> Dict[str, Any]:
    q = str(query or "").lower()
    c = constraints or {}
    explicit_with = any(t in q for t in _GPU_WITH_TERMS) or ("gpu:discrete" in [str(s).lower() for s in (c.get("specs") or [])])
    explicit_without = any(t in q for t in _GPU_WITHOUT_TERMS)
    use_case = str(c.get("use_case") or "").lower()
    use_case_tags = [str(x).lower() for x in (c.get("use_case_tags") or [])]
    likely_gpu_tasks = (
        any(t in q for t in _GPU_TASK_TERMS)
        or use_case in ("ai_ml_workstation", "gaming", "content_creation", "content_creator", "engineering_student", "architecture_student")
        or any(t in ("ai_ml_workstation", "gaming", "content_creation", "content_creator", "engineering_student", "architecture_student") for t in use_case_tags)
    )
    return {
        "likely_gpu_tasks": bool(likely_gpu_tasks),
        "explicit_with_gpu": bool(explicit_with),
        "explicit_without_gpu": bool(explicit_without),
    }
