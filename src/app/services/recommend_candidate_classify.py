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


def brand_sql_predicate(brand: str | None) -> str:
    key = str(brand or "").strip().lower()
    if key == "apple":
        return "(LOWER(p.name) LIKE '%apple%' OR LOWER(p.name) LIKE '%macbook%' OR LOWER(p.name) LIKE '%imac%' OR LOWER(p.sku) LIKE 'mb%')"
    if key == "asus":
        return "(LOWER(p.name) LIKE '%asus%' OR LOWER(p.name) LIKE '%vivobook%' OR LOWER(p.name) LIKE '%zenbook%' OR LOWER(p.name) LIKE '%rog%' OR LOWER(p.name) LIKE '%tuf%')"
    if key == "lenovo":
        return "(LOWER(p.name) LIKE '%lenovo%' OR LOWER(p.name) LIKE '%ideapad%' OR LOWER(p.name) LIKE '%thinkpad%' OR LOWER(p.name) LIKE '%yoga%' OR LOWER(p.name) LIKE '%legion%')"
    if key == "hp":
        return "(LOWER(p.name) LIKE '%hp %' OR LOWER(p.name) LIKE 'hp %' OR LOWER(p.name) LIKE '%envy%' OR LOWER(p.name) LIKE '%victus%' OR LOWER(p.name) LIKE '%omen%' OR LOWER(p.name) LIKE '%omnibook%' OR LOWER(p.name) LIKE '%elitebook%' OR LOWER(p.name) LIKE '%probook%')"
    if key == "dell":
        return "(LOWER(p.name) LIKE '%dell%' OR LOWER(p.name) LIKE '%inspiron%' OR LOWER(p.name) LIKE '%xps%' OR LOWER(p.name) LIKE '%latitude%' OR LOWER(p.name) LIKE '%vostro%')"
    if key == "msi":
        return "(LOWER(p.name) LIKE '%msi%' OR LOWER(p.name) LIKE '%stealth%' OR LOWER(p.name) LIKE '%raider%' OR LOWER(p.name) LIKE '%titan%')"
    if key == "alienware":
        return "(LOWER(p.name) LIKE '%alienware%')"
    if key == "microsoft":
        return "(LOWER(p.name) LIKE '%microsoft%' OR LOWER(p.name) LIKE '%surface%')"
    if key == "acer":
        return "(LOWER(p.name) LIKE '%acer%' OR LOWER(p.name) LIKE '%swift%' OR LOWER(p.name) LIKE '%aspire%' OR LOWER(p.name) LIKE '%predator%' OR LOWER(p.name) LIKE '%nitro%')"
    if key == "samsung":
        return "(LOWER(p.name) LIKE '%samsung%' OR LOWER(p.name) LIKE '%galaxy book%')"
    if key == "razer":
        return "(LOWER(p.name) LIKE '%razer%' OR LOWER(p.name) LIKE '%blade%')"
    if key == "gigabyte":
        return "(LOWER(p.name) LIKE '%gigabyte%' OR LOWER(p.name) LIKE '%aorus%')"
    if key == "toshiba":
        return "(LOWER(p.name) LIKE '%toshiba%' OR LOWER(p.name) LIKE '%dynabook%')"
    if key == "windows":
        return "(LOWER(p.name) NOT LIKE '%apple%' AND LOWER(p.name) NOT LIKE '%macbook%' AND LOWER(p.name) NOT LIKE '%imac%' AND LOWER(p.sku) NOT LIKE 'mb%')"
    return ""


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
