"""Intent → Requirements Resolver (V2 — the unifying mechanism, analysis doc 2026-07-12).

The five failure modes (persona-blind, software-workload-blind, multi-intent collapse,
budget→requirement bleed, useless clarify) are ONE missing mechanism. This is it:

  model classifies use_case_key(s)   [unbounded phrase → bounded KB key, CLAMPED — folded into
                                      the EXISTING router call, so ZERO added latency]
  → deterministic KB profile lookup  [config/use_case_kb.json — 'for AutoCAD' is a DATA row,
                                      never an `if` branch: the anti-treadmill guarantee]
  → convert to fit requirements      [ram_gb_min→(ram_gb,>=,16), gpu_tier→vram floor, …]
  → MULTI-INTENT merge by MAX        [most-demanding wins = the safe recommendation]
  → merge with the model's explicit  [`144fps`→refresh_hz>=144] requirements, MAX again.

Vertical-blind: the resolver is intent→profile→requirements; the profiles are DATA. The same
code serves pharma/fashion/furniture with a different KB. Deterministic + cached; never raises.

The requirement NUMBERS live in the KB (reviewed as data), never invented by the model — the
model only maps the phrase to a key. That is the doctrine (model-judged, clamped, grounded).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("shopsquire.recommendation_core.intent_resolver")

# recommendation_core is one level deeper than src/app/services → repo root is parents[4]
_KB_PATH = Path(__file__).resolve().parents[4] / "config" / "use_case_kb.json"

# KB required_specs key → (attribute-registry key, op). Numeric hard requirements only;
# descriptive prefs (ir_camera, display_color_gamut, webcam) stay soft and are not gated.
_SPEC_MAP: Dict[str, Tuple[str, str]] = {
    "ram_gb_min": ("ram_gb", ">="),
    "storage_gb_min": ("storage_gb", ">="),
    "refresh_hz_min": ("refresh_hz", ">="),
    "battery_hr_min": ("battery_hours", ">="),
    "gpu_vram_gb_min": ("gpu_vram_gb", ">="),
}
# gpu_tier (a class, not a number) → a VRAM floor (vertical-blind translation; the legacy
# gpu_translation module does the desktop↔laptop nuance — reused later).
_GPU_TIER_VRAM = {"discrete": 4, "discrete_6gb": 6, "discrete_8gb": 8}


@lru_cache(maxsize=1)
def _kb() -> Dict[str, Any]:
    try:
        return json.loads(_KB_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("use_case_kb unreadable (%s): %s", _KB_PATH, exc)
        return {"use_cases": {}, "use_case_aliases": {}}


def known_use_cases() -> List[str]:
    """The closed vocabulary the router clamps the model to."""
    return sorted((_kb().get("use_cases") or {}).keys())


def normalize_use_case(raw: str) -> Optional[str]:
    """Map a model-returned key or alias to a real KB use_case, or None (dropped)."""
    kb = _kb()
    key = str(raw or "").strip().lower().replace(" ", "_")
    if key in (kb.get("use_cases") or {}):
        return key
    alias = (kb.get("use_case_aliases") or {}).get(str(raw or "").strip().lower())
    return alias if alias in (kb.get("use_cases") or {}) else None


def _profile_constraints(use_case: str):
    """One use-case's required_specs → ConstraintMap, every bound provenance-tagged
    'use_case:<key>' (M2-B1: ranges + provenance replace the (op,thr) one-slot)."""
    from src.app.services.recommendation_core.constraints import from_op, merge
    specs = ((_kb().get("use_cases") or {}).get(use_case) or {}).get("required_specs") or {}
    src = f"use_case:{use_case}"
    out: Dict[str, Any] = {}
    for spec_key, val in specs.items():
        c = None
        if spec_key in _SPEC_MAP and isinstance(val, (int, float)):
            attr, op = _SPEC_MAP[spec_key]
            c = from_op(attr, op, float(val), src)
        elif spec_key == "gpu_tier" and str(val) in _GPU_TIER_VRAM:
            c = from_op("gpu_vram_gb", ">=", float(_GPU_TIER_VRAM[str(val)]), src)
        if c is not None:
            out[c.key] = merge(out[c.key], c) if c.key in out else c
    return out


def _legacy_min_to_fit(reqs: Dict[str, Any]) -> Dict[str, Tuple[str, float]]:
    """Convert legacy match_game/software_requirements → fit requirements, using the MINIMUM
    floors for retrieval (the min-vs-recommended P0 lesson: recommended floors zero the
    catalog; recommended drives the fit VERDICT, not elimination)."""
    out: Dict[str, Tuple[str, float]] = {}
    if reqs.get("min_ram_gb"):
        out["ram_gb"] = (">=", float(reqs["min_ram_gb"]))
    if reqs.get("min_gpu_vram_gb"):
        out["gpu_vram_gb"] = (">=", float(reqs["min_gpu_vram_gb"]))
    if reqs.get("min_refresh_hz") and reqs["min_refresh_hz"] > 60:
        out["refresh_hz"] = (">=", float(reqs["min_refresh_hz"]))
    return out


def _salvage_title_requirements(query: str) -> Dict[str, Any]:
    """SALVAGE the proven legacy per-title requirement DBs (Steam-backed games + software
    specs). 'valorant' gets valorant's floors, not the generic gaming profile — the
    requirements-grounded loop, done by reuse. Recommended floors captured for the lagginess
    verdict. Best-effort; the KB use-case profiles are the fallback."""
    out: Dict[str, Any] = {"requirements": {}, "trace": {}}
    try:
        from src.app.flows.nqe import detect_games_in_text, detect_software_in_text
        from src.app.services.use_case_advisor import (match_game_requirements,
                                                       match_software_requirements)
        from src.app.services.recommendation_core.constraints import from_op_map, merge_maps
        games = detect_games_in_text(query or "")
        software = detect_software_in_text(query or "")
        if games:
            gr = match_game_requirements(games)
            out["requirements"] = merge_maps(out["requirements"],
                                             from_op_map(_legacy_min_to_fit(gr), "title:game"))
            out["trace"]["games"] = {"matched": gr.get("games_matched", []), "tier": gr.get("tier"),
                                     "recommended_ram_gb": gr.get("recommended_ram_gb"),
                                     "recommended_gpu_vram_gb": gr.get("recommended_gpu_vram_gb")}
        if software:
            sr = match_software_requirements(software)
            out["requirements"] = merge_maps(out["requirements"],
                                             from_op_map(_legacy_min_to_fit(sr), "title:software"))
            out["trace"]["software"] = {"matched": sr.get("software_matched", []),
                                        "recommended_ram_gb": sr.get("recommended_ram_gb"),
                                        "recommended_gpu_vram_gb": sr.get("recommended_gpu_vram_gb")}
    except Exception as exc:
        logger.debug("title-requirements salvage skipped: %s", repr(exc)[:100])
    return out


def resolve(use_cases: Optional[List[str]],
            model_requirements: Optional[Dict[str, Any]] = None,
            query: Optional[str] = None) -> Dict[str, Any]:
    """The resolver (M2-B1: RANGES + provenance + surfaced conflicts). Returns:
      requirements  — {key: [(op, thr), ...]} — KB profiles ∪ per-title ∪ model-stated merged
                      by INTERSECTION (floors max, ceilings min; a floor AND a ceiling coexist
                      as a range). CONFLICTED keys are EXCLUDED (contradictions never gate).
      constraints   — {key: {lower, upper, preferred, provenance, conflict}} — full fidelity.
      conflicts     — the surfaced empty-range keys ('nothing over 8GB' vs a KB floor of 16):
                      clarify material, NEVER silently resolved in either side's favour.
      use_cases / profile_trace / title_requirements / persona_hint — as before.
    Multi-intent falls out naturally: ['gaming','creative'] → intersection of both profiles."""
    from src.app.services.recommendation_core.constraints import (
        as_dicts, conflicts as constraint_conflicts, from_op_map, merge_maps, project)
    resolved: List[str] = []
    for uc in (use_cases or []):
        n = normalize_use_case(uc)
        if n and n not in resolved:
            resolved.append(n)

    merged: Dict[str, Any] = {}
    profile_trace: Dict[str, Dict[str, Any]] = {}
    for uc in resolved:
        prof = _profile_constraints(uc)
        profile_trace[uc] = {"requirements": {k: [list(p) for p in c.predicates()]
                                              for k, c in prof.items()},
                             "label": ((_kb().get("use_cases") or {}).get(uc) or {}).get("label", uc)}
        merged = merge_maps(merged, prof)
    # SALVAGE: per-title (game/software) requirements from the proven legacy DBs
    title = _salvage_title_requirements(query) if query else {"requirements": {}, "trace": {}}
    if title["requirements"]:
        merged = merge_maps(merged, title["requirements"])
    # the model's explicitly-stated requirements ('144fps', 'nothing over 8GB') — provenance
    # 'stated'; a stated ceiling meeting a KB floor becomes a RANGE or a surfaced conflict.
    if model_requirements:
        merged = merge_maps(merged, from_op_map(dict(model_requirements), "stated"))

    persona_hint = None
    if resolved:
        persona_hint = ((_kb().get("use_cases") or {}).get(resolved[0]) or {}).get("nqe_persona")

    return {"requirements": project(merged), "constraints": as_dicts(merged),
            "conflicts": constraint_conflicts(merged), "use_cases": resolved,
            "profile_trace": profile_trace, "title_requirements": title["trace"],
            "persona_hint": persona_hint}
