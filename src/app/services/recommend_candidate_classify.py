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
import re
from functools import lru_cache
from typing import Any, Dict, Optional

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


# ─────────────────────────────────────────────────────────────────────────────
# ADAPTER: GPU capability tier + use-case fit (electronics-specific knowledge).
#
# Core ranking (recommend.py) MUST NOT hardcode "rtx == good", "arc == gaming",
# etc. It calls use_case_fit(candidate, query) and applies a generic boost when
# `meets` is True. The electronics-specific judgments — which GPU strings are
# discrete vs integrated, what each use-case requires — live HERE and read their
# thresholds from the active store profile (config/store_profiles/<id>.json:
# use_cases, use_case_patterns). A non-electronics tenant supplies its own
# adapter; the core is unchanged.
# ─────────────────────────────────────────────────────────────────────────────

# Integrated / weak-for-3D GPU markers. Intel Arc is an *integrated* iGPU tier
# (entry productivity), NOT a discrete gaming part — this is the crux of the
# "Intel Arc ranked as a gaming match" defect.
_INTEGRATED_GPU_MARKERS = (
    "intel arc", "arc graphics", "iris", "uhd graphics", "hd graphics",
    "integrated", "igpu", "adreno", "radeon graphics", "radeon 6", "radeon 7",
    "radeon 8", "vega",
)


def _to_int(val: Any) -> Optional[int]:
    try:
        if val is None or isinstance(val, bool):
            return None
        return int(float(str(val).strip().lower().rstrip("gbhz ")))
    except Exception:
        return None


def gpu_tier(candidate: Dict[str, Any] | None) -> str:
    """Coarse GPU capability tier for ranking: one of
    'none' < 'integrated' < 'entry' < 'mid' < 'high'.

    Brand-agnostic *within electronics*: discrete NVIDIA (RTX/GTX) and AMD (RX)
    are tiered by model band; Intel Arc/Iris/UHD and Qualcomm Adreno and AMD APU
    "Radeon Graphics" are integrated. Used to gate use-case fit (e.g. gaming and
    video editing require a discrete tier)."""
    c = candidate or {}
    specs = c.get("specs") if isinstance(c.get("specs"), dict) else {}
    gpu_str = str(specs.get("gpu") or specs.get("graphics") or "").lower()
    blob = f"{gpu_str} {str(c.get('name') or '').lower()}"

    # Discrete NVIDIA GeForce: tier by the last two model digits (e.g. 4070 -> 70).
    m = re.search(r"\b(?:rtx|gtx)\s*(\d{3,4})", blob)
    if m:
        last2 = int(m.group(1)) % 100
        if last2 >= 70:
            return "high"
        if last2 >= 60:
            return "mid"
        return "entry"
    # Discrete AMD Radeon RX (avoid matching integrated "Radeon Graphics").
    # AMD encodes tier in the hundreds digit (RX 7700 -> 7 high, 7600 -> 6 mid),
    # unlike NVIDIA's last-two-digits scheme above.
    m = re.search(r"\brx\s*(\d{3,4})", blob)
    if m:
        tier_digit = (int(m.group(1)) // 100) % 10
        if tier_digit >= 7:
            return "high"
        if tier_digit == 6:
            return "mid"
        return "entry"
    if any(t in blob for t in _INTEGRATED_GPU_MARKERS):
        return "integrated"
    # Discrete markers without a parseable model number.
    if any(t in blob for t in ("geforce", "quadro", "radeon pro", "discrete", "dgpu")):
        return "entry"
    if gpu_str:
        # Has a GPU string we couldn't classify -> assume integrated, never gaming-grade.
        return "integrated"
    return "none"


_DISCRETE_TIERS = ("entry", "mid", "high")


def use_case_fit(
    candidate: Dict[str, Any] | None,
    query: str | None,
    *,
    constraints: Dict[str, Any] | None = None,
    profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    """ADAPTER entry the core calls once per candidate.

    Resolves the shopper's use-case from the query (profile use_case_patterns),
    looks up that use-case's requirements (profile use_cases: needs_dedicated_gpu,
    spec_floors) and checks the candidate against them. Returns:

        {
          "use_case": str | None,     # resolved use-case, or None if generic
          "meets": bool,              # candidate satisfies every requirement
          "tier": str,                # gpu_tier(candidate)
          "reasons": [str, ...],      # positive reason codes (first is
                                      #   "<use_case>_use_case_match" when meets)
          "gaps":   [str, ...],       # unmet-requirement codes
        }

    Critically, "<use_case>_use_case_match" is emitted ONLY when the candidate
    actually meets the requirements — so a 60Hz Intel-Arc laptop is no longer
    tagged as a gaming match just because the query says "gaming"."""
    from src.app.platform.store_profile import profile_slot

    c = candidate or {}
    tier = gpu_tier(c)
    result: Dict[str, Any] = {"use_case": None, "meets": True, "tier": tier, "reasons": [], "gaps": []}
    q = str(query or "").lower()
    if not q:
        return result

    try:
        patterns = profile_slot("use_case_patterns", profile_id=profile_id, default={}) or {}
        use_cases = profile_slot("use_cases", profile_id=profile_id, default={}) or {}
    except Exception:
        return result

    resolved = None
    for uc, pat in patterns.items():
        try:
            if pat and re.search(pat, q):
                resolved = uc
                break
        except re.error:
            continue
    result["use_case"] = resolved
    if not resolved:
        return result

    reqs = use_cases.get(resolved) or {}
    specs = c.get("specs") if isinstance(c.get("specs"), dict) else {}
    discrete = tier in _DISCRETE_TIERS
    meets = True

    if reqs.get("needs_dedicated_gpu"):
        if discrete:
            result["reasons"].append("discrete_gpu")
        else:
            meets = False
            result["gaps"].append(f"needs_discrete_gpu_for_{resolved}")

    floors = reqs.get("spec_floors") or {}
    refresh_min = floors.get("refresh_hz_min")
    if refresh_min is not None:
        hz = _to_int(specs.get("refresh_hz"))
        if hz is not None and hz >= int(refresh_min):
            result["reasons"].append("high_refresh_display")
        elif hz is not None:
            meets = False
            result["gaps"].append(f"refresh_below_{int(refresh_min)}hz")
    ram_min = floors.get("ram_gb_min")
    if ram_min is not None:
        ram = _to_int(specs.get("ram_gb"))
        if ram is not None and ram >= int(ram_min):
            result["reasons"].append("ram_meets_workload")
        elif ram is not None:
            meets = False
            result["gaps"].append(f"ram_below_{int(ram_min)}gb")

    result["meets"] = meets
    if meets:
        result["reasons"].insert(0, f"{resolved}_use_case_match")
    return result
