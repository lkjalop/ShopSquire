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

from functools import lru_cache
from typing import Any, Dict, List, Tuple

from src.app.services.recommend_utils import _extract_candidate_numeric_specs


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Generic ranking-rule evaluator driven by StoreProfile["ranking_rules"].
# A rule = {use_cases:[...], match_query:[...], conditions:[{metric, op, value, delta, reason}]}.
# A rule fires when the use_case matches (or a match_query token is in the query); each satisfied
# condition adds its delta and a reason. Verticals WITHOUT the slot fall back to the electronics
# inline scorer below (byte-identical). Metrics come from spec_extraction_rules (also profile).
# ═══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=8)
def _ranking_rules_for(pid: str):
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("ranking_rules", profile_id=pid, default=None)
    return raw if isinstance(raw, list) and raw else None


def _active_pid() -> str:
    from src.app.platform.store_profile import active_profile_id
    return active_profile_id()


def reset_cache() -> None:
    """Clear the per-profile ranking-rules cache (test isolation / reload)."""
    _ranking_rules_for.cache_clear()


def _condition_met(metric_value: Any, op: str, value: Any) -> bool:
    op = str(op or "truthy").lower()
    if op == "truthy":
        return bool(metric_value)
    if op == "falsy":
        return not bool(metric_value)
    try:
        x = float(metric_value) if metric_value is not None else None
    except Exception:
        x = None
    if x is None:
        return False
    try:
        if op == ">=":
            return x >= float(value)
        if op == "<=":
            return x <= float(value)
        if op == ">":
            return x > float(value)
        if op == "<":
            return x < float(value)
        if op == "==":
            return x == float(value)
        if op == "between" and isinstance(value, (list, tuple)) and len(value) == 2:
            return float(value[0]) <= x <= float(value[1])
    except (TypeError, ValueError):
        return False
    return False


def _evaluate_ranking_rules(
    metrics: Dict[str, Any], use_case: str, query: str, rules: list
) -> Tuple[float, List[str], List[str]]:
    uc = str(use_case or "").strip().lower()
    q = str(query or "").lower()
    score = 0.0
    plus: List[str] = []
    minus: List[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        ucs = [str(x).lower() for x in (rule.get("use_cases") or [])]
        mq = [str(x).lower() for x in (rule.get("match_query") or [])]
        if not (uc in ucs or any(t in q for t in mq)):
            continue
        for cond in rule.get("conditions") or []:
            if not isinstance(cond, dict):
                continue
            if _condition_met(metrics.get(cond.get("metric")), cond.get("op"), cond.get("value")):
                delta = float(cond.get("delta") or 0.0)
                score += delta
                reason = cond.get("reason")
                if reason:
                    (plus if delta >= 0 else minus).append(str(reason))
    return round(score, 4), plus[:3], minus[:3]


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER — Electronics-specific use-case rank scoring (inline fallback).
# Used only when the active profile defines no ranking_rules. Every metric and
# threshold here is laptop/electronics flavour.
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

    # Profile-driven path (vertical-agnostic): use the rule table if the active profile defines one.
    _rules = _ranking_rules_for(_active_pid())
    if _rules is not None:
        return _evaluate_ranking_rules(_extract_candidate_numeric_specs(candidate), use_case, q_low, _rules)

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
