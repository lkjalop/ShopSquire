"""Use-Case Advisor — resolves a use-case tag to minimum hardware specs and apps.

Loads the structured knowledge base from config/use_case_knowledge_base.json
and provides lookup + suitability assessment functions for the recommendation
pipeline.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional


_KB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "use_case_knowledge_base.json")
_MIN_VIABLE_KB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "use_case_knowledge.json")


@lru_cache(maxsize=1)
def _load_kb() -> Dict[str, Any]:
    path = os.path.normpath(_KB_PATH)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_min_viable_kb() -> Dict[str, Any]:
    path = os.path.normpath(_MIN_VIABLE_KB_PATH)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_use_case_specs(use_case_key: str) -> Dict[str, Any] | None:
    """Return the spec requirements for a given use-case key, or None."""
    kb = _load_kb()
    cases = kb.get("use_cases") or {}
    return cases.get(use_case_key)


def get_use_case_min_price_floor(use_case_key: str) -> Optional[int]:
    """Return minimum viable budget floor for a use-case key, if configured."""
    if not use_case_key:
        return None
    try:
        kb2 = _load_min_viable_kb()
        row = (kb2.get("use_cases") or {}).get(use_case_key) or {}
        for key in ("min_price_floor", "min_price", "price_floor"):
            if row.get(key) is not None:
                return int(float(row.get(key)))
    except Exception:
        pass
    # Fallback to base KB if min floor is embedded there.
    try:
        base = get_use_case_specs(use_case_key) or {}
        for key in ("min_price_floor", "min_price", "price_floor"):
            if base.get(key) is not None:
                return int(float(base.get(key)))
    except Exception:
        pass
    return None


def list_use_cases() -> List[str]:
    """Return all known use-case keys."""
    kb = _load_kb()
    return list((kb.get("use_cases") or {}).keys())


def match_use_case_from_query(query: str) -> Optional[str]:
    """Best-effort match a user query to a use-case key via keyword mapping."""
    q = (query or "").lower()
    keyword_map = {
        "university_general": ["university", "school", "college", "student", "study", "coursework"],
        "engineering_student": ["engineering", "cad", "autocad", "solidworks", "mechanical", "civil eng"],
        "computer_science_student": ["computer science", "compsci", "cs student", "programming student", "coding student", "software dev"],
        "data_science_student": ["data science", "machine learning student", "ml student", "data analytics"],
        "design_student": ["graphic design", "visual arts", "design student", "illustrat"],
        "gaming_casual": ["casual gam", "light gaming", "some games"],
        "gaming_competitive": ["competitive gam", "esports", "high fps", "144hz", "240hz"],
        "gaming_light": ["minecraft", "roblox", "league of legends", "lol", "indie game"],
        "gaming_aaa_heavy": ["cyberpunk", "space marines", "starfield", "aaa gam", "ultra settings", "4k gaming"],
        "content_creator": ["video edit", "content creat", "youtube", "streaming", "premiere", "davinci"],
        "business_professional": ["business", "office work", "corporate", "enterprise", "professional"],
        "office_general": ["general office", "email", "teams", "admin", "clerical"],
        "office_finance": ["finance", "accounting", "excel", "spreadsheet", "power bi", "tableau", "sap", "bloomberg"],
        "office_executive": ["executive", "c-suite", "ceo", "cfo", "director", "boardroom", "travel laptop"],
        "note_taking_student": ["note taking", "handwriting", "stylus", "pen input", "2-in-1", "tablet mode"],
        "ai_ml_workstation": ["ai training", "deep learning", "model training", "cuda", "ml workstation", "llm training"],
        "music_production": ["music prod", "audio engineer", "daw", "ableton", "fl studio", "logic pro"],
        "architecture_student": ["architect", "revit", "sketchup", "3d render"],
        "medical_student": ["medical student", "anatomy", "medical school", "clinical rotation"],
        "law_student": ["law student", "legal", "case brief", "law school"],
    }
    best_key = None
    best_score = 0
    for key, keywords in keyword_map.items():
        score = sum(1 for kw in keywords if kw in q)
        if score > best_score:
            best_score = score
            best_key = key
    return best_key if best_score > 0 else None


def assess_suitability(
    use_case_key: str,
    product_specs: Dict[str, Any],
) -> Dict[str, Any]:
    """Check if a product meets the minimum specs for a use-case.

    product_specs should have keys like: ram_gb, storage_gb, has_dedicated_gpu,
    gpu_vram_gb, display_inches, cpu_tier, refresh_hz.

    Returns: {suitable: bool, verdict: str, gaps: [...], strengths: [...]}
    """
    reqs = get_use_case_specs(use_case_key)
    if not reqs:
        return {"suitable": True, "verdict": "unknown_use_case", "gaps": [], "strengths": []}

    gaps: List[str] = []
    strengths: List[str] = []
    excess: List[str] = []
    overkill_score = 0.0
    _overkill_signals = 0
    _overkill_total = 0

    # RAM
    ram = product_specs.get("ram_gb")
    if ram and isinstance(ram, (int, float)):
        min_ram = reqs.get("min_ram_gb") or 0
        rec_ram = reqs.get("recommended_ram_gb") or min_ram
        if ram < min_ram:
            gaps.append(f"RAM {ram}GB below minimum {min_ram}GB")
        elif ram >= rec_ram:
            strengths.append(f"RAM {ram}GB meets/exceeds recommended {rec_ram}GB")
        # Overkill: RAM vastly exceeds recommended (3x+)
        if rec_ram and rec_ram > 0:
            _overkill_total += 1
            ratio = ram / rec_ram
            if ratio >= 3.0:
                excess.append(f"RAM {ram}GB is {ratio:.0f}x the recommended {rec_ram}GB")
                _overkill_signals += 1

    # Storage
    storage = product_specs.get("storage_gb")
    if storage and isinstance(storage, (int, float)):
        min_storage = reqs.get("min_storage_gb") or 0
        if storage < min_storage:
            gaps.append(f"Storage {storage}GB below minimum {min_storage}GB")
        else:
            strengths.append(f"Storage {storage}GB sufficient")
        # Overkill: storage vastly exceeds minimum (4x+)
        if min_storage and min_storage > 0:
            _overkill_total += 1
            ratio = storage / min_storage
            if ratio >= 4.0:
                excess.append(f"Storage {storage}GB is {ratio:.0f}x the minimum {min_storage}GB")
                _overkill_signals += 1

    # GPU
    gpu_needed = reqs.get("gpu_needed")
    has_gpu = product_specs.get("has_dedicated_gpu", False)
    if gpu_needed is True and not has_gpu:
        gaps.append(f"Dedicated GPU required: {reqs.get('gpu_note', 'needed for this workload')}")
    elif gpu_needed is True and has_gpu:
        strengths.append("Has dedicated GPU as required")
    # Overkill: dedicated GPU present but not needed for use-case
    if gpu_needed is False and has_gpu:
        _overkill_total += 1
        excess.append("Has dedicated GPU, but not needed for this use-case")
        _overkill_signals += 1

    # VRAM
    min_vram = reqs.get("min_gpu_vram_gb")
    actual_vram = product_specs.get("gpu_vram_gb")
    if min_vram and actual_vram and isinstance(actual_vram, (int, float)):
        if actual_vram < min_vram:
            gaps.append(f"GPU VRAM {actual_vram}GB below minimum {min_vram}GB")
        # Overkill: VRAM vastly exceeds minimum (3x+)
        if min_vram > 0:
            _overkill_total += 1
            ratio = actual_vram / min_vram
            if ratio >= 3.0:
                excess.append(f"GPU VRAM {actual_vram}GB is {ratio:.0f}x the minimum {min_vram}GB")
                _overkill_signals += 1

    # Display
    min_display = reqs.get("min_display_inches")
    actual_display = product_specs.get("display_inches")
    if min_display and actual_display and isinstance(actual_display, (int, float)):
        if actual_display < min_display:
            gaps.append(f"Display {actual_display}\" below minimum {min_display}\"")

    # Refresh rate
    min_hz = reqs.get("min_refresh_hz")
    actual_hz = product_specs.get("refresh_hz")
    if min_hz and actual_hz and isinstance(actual_hz, (int, float)):
        if actual_hz < min_hz:
            gaps.append(f"Refresh rate {actual_hz}Hz below minimum {min_hz}Hz")

    # Compute overkill score (0.0 = right-sized, 1.0 = extreme overkill)
    if _overkill_total > 0:
        overkill_score = round(_overkill_signals / _overkill_total, 2)

    suitable = len(gaps) == 0
    if suitable and overkill_score >= 0.6:
        verdict = "overkill"
    elif suitable:
        verdict = "fully_suitable"
    elif len(gaps) <= 1:
        verdict = "mostly_suitable"
    else:
        verdict = "not_ideal"

    return {
        "suitable": suitable,
        "verdict": verdict,
        "gaps": gaps,
        "strengths": strengths,
        "excess": excess,
        "overkill_score": overkill_score,
        "use_case_label": reqs.get("label", use_case_key),
        "required_apps": reqs.get("apps", []),
        "priority_factors": reqs.get("priority_factors", []),
    }


# ── Game requirements aggregation ──

def get_game_specs(game_slug: str) -> Dict[str, Any] | None:
    """Return specs for a single game slug, or None."""
    kb = _load_kb()
    return (kb.get("game_requirements") or {}).get(game_slug)


def match_game_requirements(game_slugs: List[str]) -> Dict[str, Any]:
    """Aggregate hardware requirements across multiple detected games.

    Returns the *maximum* needed across all games so the machine can run every
    title the user mentioned.
    """
    kb = _load_kb()
    games_db = kb.get("game_requirements") or {}
    result: Dict[str, Any] = {
        "tier": "light",
        "min_ram_gb": 0,
        "recommended_ram_gb": 0,
        "gpu_needed": False,
        "min_gpu_vram_gb": 0,
        "recommended_gpu_vram_gb": 0,
        "min_refresh_hz": 60,
        "games_matched": [],
        "games_not_found": [],
    }
    tier_order = {"light": 0, "casual": 1, "competitive": 2, "aaa_medium": 3, "aaa_heavy": 4}
    best_tier_rank = 0

    for slug in game_slugs:
        spec = games_db.get(slug)
        if not spec:
            result["games_not_found"].append(slug)
            continue
        result["games_matched"].append(slug)
        # Aggregate maximums
        result["min_ram_gb"] = max(result["min_ram_gb"], spec.get("min_ram_gb", 0))
        result["recommended_ram_gb"] = max(result["recommended_ram_gb"], spec.get("recommended_ram_gb", 0))
        if spec.get("gpu_needed"):
            result["gpu_needed"] = True
        result["min_gpu_vram_gb"] = max(result["min_gpu_vram_gb"], spec.get("min_gpu_vram_gb", 0))
        result["recommended_gpu_vram_gb"] = max(
            result["recommended_gpu_vram_gb"], spec.get("recommended_gpu_vram_gb", 0)
        )
        target_fps = spec.get("target_fps", 60)
        if target_fps >= 144:
            result["min_refresh_hz"] = max(result["min_refresh_hz"], 144)
        tier = spec.get("tier", "light")
        rank = tier_order.get(tier, 0)
        if rank > best_tier_rank:
            best_tier_rank = rank
            result["tier"] = tier

    return result


# ── Software requirements aggregation ──

def get_software_specs(software_slug: str) -> Dict[str, Any] | None:
    """Return specs for a single software slug, or None."""
    kb = _load_kb()
    return (kb.get("software_requirements") or {}).get(software_slug)


def get_accessory_affinities(use_case_key: str | None) -> List[str]:
    """Return ordered accessory category slugs to boost for a given use-case.

    Always prepends the universal accessories (screen protector, sleeve, etc.)
    then appends use-case-specific items.  Deduplicates while preserving order.
    """
    kb = _load_kb()
    affinities: dict = kb.get("accessory_affinities") or {}
    universal: List[str] = list(affinities.get("_universal") or [])
    specific: List[str] = []
    if use_case_key:
        specific = list(affinities.get(use_case_key) or [])
    combined: List[str] = []
    seen: set = set()
    for slug in specific + universal:  # specific first (higher priority)
        if slug not in seen:
            seen.add(slug)
            combined.append(slug)
    return combined


def get_use_case_priority_factors(use_case_key: str | None) -> List[str]:
    """Return priority_factors list for a use-case key, or empty list."""
    if not use_case_key:
        return []
    spec = get_use_case_specs(use_case_key)
    if not spec:
        return []
    return list(spec.get("priority_factors") or [])


def match_software_requirements(software_slugs: List[str]) -> Dict[str, Any]:
    """Aggregate hardware requirements across multiple detected software titles."""
    kb = _load_kb()
    sw_db = kb.get("software_requirements") or {}
    result: Dict[str, Any] = {
        "min_ram_gb": 0,
        "recommended_ram_gb": 0,
        "gpu_needed": False,
        "min_gpu_vram_gb": 0,
        "recommended_gpu_vram_gb": 0,
        "software_matched": [],
        "software_not_found": [],
    }

    for slug in software_slugs:
        spec = sw_db.get(slug)
        if not spec:
            result["software_not_found"].append(slug)
            continue
        result["software_matched"].append(slug)
        result["min_ram_gb"] = max(result["min_ram_gb"], spec.get("min_ram_gb", 0))
        result["recommended_ram_gb"] = max(result["recommended_ram_gb"], spec.get("recommended_ram_gb", 0))
        if spec.get("gpu_needed"):
            result["gpu_needed"] = True
        result["min_gpu_vram_gb"] = max(result["min_gpu_vram_gb"], spec.get("min_gpu_vram_gb", 0))
        result["recommended_gpu_vram_gb"] = max(
            result["recommended_gpu_vram_gb"], spec.get("recommended_gpu_vram_gb", 0)
        )

    return result


# ── Touch screen / form-factor suitability ──

def assess_touch_screen_suitability(
    product_specs: Dict[str, Any],
    needs_pen: bool = False,
) -> Dict[str, Any]:
    """Check if a product meets touch screen / pen input requirements.

    product_specs should have: has_touch_screen (bool), has_pen_support (bool),
    form_factor (str, e.g. '2-in-1', 'convertible', 'clamshell').
    """
    has_touch = product_specs.get("has_touch_screen", False)
    has_pen = product_specs.get("has_pen_support", False)
    form = (product_specs.get("form_factor") or "").lower()

    gaps: List[str] = []
    strengths: List[str] = []

    if not has_touch:
        gaps.append("No touch screen — required for note-taking or drawing")
    else:
        strengths.append("Touch screen available")

    if needs_pen and not has_pen:
        gaps.append("No pen/stylus support — needed for handwritten notes or drawing")
    elif needs_pen and has_pen:
        strengths.append("Pen/stylus support available")

    if form in ("2-in-1", "convertible"):
        strengths.append(f"Form factor '{form}' well-suited for touch/pen use")

    return {
        "suitable": len(gaps) == 0,
        "gaps": gaps,
        "strengths": strengths,
    }
