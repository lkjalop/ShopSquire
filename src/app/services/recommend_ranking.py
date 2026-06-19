"""Use-case-aware ranking adjustments.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
CORE (vertical-agnostic):
  • apply_use_case_rank_adjustments() — the FRAMEWORK that iterates candidates,
    calls the scoring function, merges bonuses into factors, and re-sorts.
    This works for ANY vertical.

ADAPTER (product-type-specific, currently hardcoded electronics):
  • use_case_rank_adjustment() — the BODY of this function is 100% electronics.
    It reads laptop-specific metrics (RAM GB, GPU VRAM, refresh Hz, "gaming style",
    "portable", "NVIDIA") and applies electronics-specific heuristics (gamers need
    GPU, students don't, engineers need 16GB RAM minimum, etc.).
  • _extract_candidate_numeric_specs() in recommend_utils.py — parses laptop spec
    fields (ram_gb, gpu_vram_gb, refresh_hz, display_inches).

MIGRATION PATH (Phase 2):
  Add `ranking_rules` slot to StoreProfile — a list of {use_case, spec_key, op,
  threshold, score_delta, reason} entries. The CORE framework reads these rules
  and applies them generically. Electronics rules would match the current logic;
  pharmacy rules would score on "interaction_count", "dosage_flexibility", etc.
  Transitional: inline electronics heuristics retained as fallback.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src.app.services.recommend_utils import _extract_candidate_numeric_specs


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER — Electronics-specific use-case rank scoring.
# Every metric (ram, gpu_vram, refresh_hz, gaming_style, portable, nvidia) and
# every heuristic threshold is laptop/electronics-specific.
# Phase 2: replace with profile-driven rule table from StoreProfile["ranking_rules"].
# ═══════════════════════════════════════════════════════════════════════════════

def use_case_rank_adjustment(
    candidate: Dict[str, Any],
    *,
    use_case_key: str | None,
    query: str,
) -> Tuple[float, List[str], List[str]]:
    use_case = str(use_case_key or "").strip().lower()
    q_low = str(query or "").lower()
    if not use_case:
        return 0.0, [], []

    metrics = _extract_candidate_numeric_specs(candidate)
    plus: List[str] = []
    minus: List[str] = []
    score = 0.0

    ram = float(metrics.get("ram_gb") or 0.0)
    storage = float(metrics.get("storage_gb") or 0.0)
    display = float(metrics.get("display_inches") or 0.0)
    refresh = float(metrics.get("refresh_hz") or 0.0)
    gpu_vram = float(metrics.get("gpu_vram_gb") or 0.0)
    has_gpu = bool(metrics.get("has_dedicated_gpu"))
    gaming_style = bool(metrics.get("gaming_style"))
    portable = bool(metrics.get("portable"))
    nvidia = bool(metrics.get("nvidia"))
    creator_hint = bool(metrics.get("creator_hint"))
    workstation_hint = bool(metrics.get("workstation_hint"))

    student_keys = {"high_school", "university_general", "note_taking_student", "medical_student", "law_student"}
    work_keys = {"business_professional", "office_general", "office_finance", "office_executive"}
    engineering_keys = {"engineering_student", "computer_science_student"}

    if use_case in student_keys:
        if portable:
            score += 1.1
            plus.append("portable for daily study")
        if 16 <= ram <= 32:
            score += 0.8
            plus.append("enough RAM for schoolwork")
        elif 8 <= ram < 16:
            score += 0.2
        if storage >= 512:
            score += 0.4
            plus.append("usable storage headroom")
        if has_gpu:
            score -= 0.8
            minus.append("more GPU-heavy than most school needs")
        if gaming_style:
            score -= 1.3
            minus.append("gaming-first design is less ideal for school")
        if display and display >= 15.6:
            score -= 0.35
    elif use_case in work_keys:
        if portable:
            score += 1.0
            plus.append("portable for work travel")
        if 16 <= ram <= 32:
            score += 0.7
            plus.append("fits office multitasking")
        if has_gpu and not creator_hint:
            score -= 0.7
            minus.append("dedicated GPU is usually unnecessary for office work")
        if gaming_style:
            score -= 1.4
            minus.append("gaming chassis is a poor fit for business use")
    elif use_case in {"gaming_casual", "gaming_competitive", "gaming_light", "gaming_aaa_heavy"} or "gaming" in q_low:
        if has_gpu:
            score += 2.0
            plus.append("dedicated GPU for gaming")
        else:
            score -= 2.4
            minus.append("no dedicated GPU for gaming")
        if ram >= 16:
            score += 0.9
            plus.append("16GB+ RAM helps gaming")
        elif ram and ram < 16:
            score -= 0.6
        if refresh >= 144:
            score += 0.8
            plus.append("high refresh display")
        if gpu_vram >= 6:
            score += 0.7
        if gaming_style:
            score += 0.5
    elif use_case in {"content_creator", "content_creation", "design_student"}:
        if ram >= 16:
            score += 0.8
            plus.append("strong RAM for editing apps")
        if storage >= 1024:
            score += 0.5
            plus.append("more storage for creator files")
        if has_gpu:
            score += 1.0
            plus.append("GPU helps creative workloads")
        if creator_hint or workstation_hint:
            score += 0.6
    elif use_case in {"ai_ml_workstation"}:
        if has_gpu:
            score += 2.2
            plus.append("dedicated GPU for local AI workloads")
        else:
            score -= 2.5
            minus.append("local AI workloads need a stronger GPU")
        if nvidia:
            score += 0.8
            plus.append("NVIDIA ecosystem is more practical for AI tooling")
        if ram >= 32:
            score += 1.0
            plus.append("32GB+ RAM is better for AI workflows")
        elif ram >= 16:
            score += 0.3
    elif use_case in {"data_science_student"}:
        if ram >= 32:
            score += 1.1
            plus.append("32GB RAM helps data workflows")
        elif ram >= 16:
            score += 0.7
            plus.append("16GB RAM is workable for notebooks and analysis")
        if storage >= 1024:
            score += 0.5
        if has_gpu:
            score += 0.5
        if nvidia:
            score += 0.4
    elif use_case in engineering_keys:
        if ram >= 16:
            score += 0.8
            plus.append("RAM headroom for coding and CAD-style tools")
        if has_gpu:
            score += 0.8
            plus.append("GPU helps engineering workloads")
        if workstation_hint:
            score += 0.4
    return round(score, 4), plus[:3], minus[:3]


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Generic ranking adjustment framework (vertical-agnostic).
# Iterates candidates, calls the scoring function, merges bonuses, re-sorts.
# The per-candidate scoring function is the ADAPTER entry point above.
# ═══════════════════════════════════════════════════════════════════════════════

def apply_use_case_rank_adjustments(
    scored: List[Dict[str, Any]],
    *,
    use_case_key: str | None,
    query: str,
) -> List[Dict[str, Any]]:
    if not scored or not use_case_key:
        return scored
    adjusted: List[Dict[str, Any]] = []
    for item in scored:
        if not isinstance(item, dict):
            continue
        candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
        bonus, plus, minus = use_case_rank_adjustment(candidate, use_case_key=use_case_key, query=query)
        new_item = dict(item)
        base_factors = dict(new_item.get("factors") or {})
        pos = [str(x) for x in (base_factors.get("positive") or [])]
        neg = [str(x) for x in (base_factors.get("negative") or [])]
        for msg in plus:
            if msg not in pos:
                pos.append(msg)
        for msg in minus:
            if msg not in neg:
                neg.append(msg)
        base_factors["positive"] = pos[:6]
        base_factors["negative"] = neg[:6]
        base_factors["use_case_bonus"] = bonus
        new_item["factors"] = base_factors
        new_item["score"] = float(new_item.get("score") or 0.0) + float(bonus)
        adjusted.append(new_item)
    adjusted.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    return adjusted
