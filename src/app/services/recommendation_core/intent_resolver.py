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
# gpu_tier (a class, not a number) → a VRAM floor (vertical-blind translation; the legacy
# gpu_translation module does the desktop↔laptop nuance — reused later).
@lru_cache(maxsize=1)
def _kb() -> Dict[str, Any]:
    try:
        return json.loads(_KB_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("use_case_kb unreadable (%s): %s", _KB_PATH, exc)
        return {"use_cases": {}, "use_case_aliases": {}}


def _registry_keys() -> frozenset:
    """The new use_case_registry's use-case vocabulary (partial KB step 3) — additive to the
    legacy KB so smart intents (drawing/creative) are classifiable at all and their capability
    predicates injectable. Best-effort; never breaks routing if the registry is unreadable."""
    try:
        from src.app.services import use_case_registry as R
        return R.all_use_case_keys()
    except Exception as exc:
        logger.debug("registry use-case keys unavailable: %s", repr(exc)[:100])
        return frozenset()


def known_use_cases() -> List[str]:
    """The closed vocabulary the router clamps the model to — legacy KB ∪ the new registry."""
    return sorted(set((_kb().get("use_cases") or {}).keys()) | set(_registry_keys()))


def normalize_use_case(raw: str) -> Optional[str]:
    """Map a model-returned key or alias to a real use_case (legacy KB or registry), or None."""
    kb = _kb()
    key = str(raw or "").strip().lower().replace(" ", "_")
    if key in (kb.get("use_cases") or {}) or key in _registry_keys():
        return key
    alias = (kb.get("use_case_aliases") or {}).get(str(raw or "").strip().lower())
    return alias if alias in (kb.get("use_cases") or {}) else None


def _ordered_use_cases(use_cases: List[str]) -> List[str]:
    """Order explanation context by profile-owned priority, preserving ties."""
    profiles = _kb().get("use_cases") or {}
    indexed = list(enumerate(use_cases))

    def key(item):
        index, use_case = item
        try:
            priority = int((profiles.get(use_case) or {}).get("resolution_priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        return (-priority, index)

    return [use_case for _, use_case in sorted(indexed, key=key)]


def _profile_constraints(use_case: str):
    """One use-case's required_specs → ConstraintMap, every bound provenance-tagged
    'use_case:<key>' (M2-B1: ranges + provenance replace the (op,thr) one-slot)."""
    from src.app.services.recommendation_core.constraints import from_op, merge
    specs = ((_kb().get("use_cases") or {}).get(use_case) or {}).get("required_specs") or {}
    numeric_mappings = _kb().get("requirement_mappings") or {}
    categorical_mappings = _kb().get("categorical_requirement_mappings") or {}
    src = f"use_case:{use_case}"
    out: Dict[str, Any] = {}
    for spec_key, val in specs.items():
        c = None
        mapping = numeric_mappings.get(spec_key) if isinstance(numeric_mappings, dict) else None
        if isinstance(mapping, dict) and isinstance(val, (int, float)):
            c = from_op(str(mapping.get("attribute") or ""), str(mapping.get("op") or ""),
                        float(val), src)
        else:
            choices = categorical_mappings.get(spec_key) if isinstance(categorical_mappings, dict) else None
            mapping = choices.get(str(val)) if isinstance(choices, dict) else None
            if isinstance(mapping, dict) and isinstance(mapping.get("value"), (int, float)):
                c = from_op(str(mapping.get("attribute") or ""), str(mapping.get("op") or ""),
                            float(mapping["value"]), src)
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


def _inject_registry_capabilities(reqs: Dict[str, Any], use_cases: List[str],
                                  vertical: Optional[str]) -> Dict[str, Any]:
    """Partial KB step 3: inject the new registry's capability predicates — boolean/enum like
    touchscreen/form_factor, which the NUMERIC constraint machinery and the legacy KB can't
    express and the router's quantity-only extraction can't emit — for the routed vertical +
    use-cases. MERGE-not-override: a key already set by legacy/stated/title WINS; the registry
    only FILLS gaps. This is what makes 'laptop for drawing' carry a touchscreen/form-factor
    floor on the LIVE path (not just in unit tests). vertical=None (ungrounded) → no injection."""
    if not vertical or not use_cases:
        return reqs
    try:
        from src.app.services import use_case_registry as R
    except Exception:
        return reqs
    out = dict(reqs)
    for uc in use_cases:
        r = R.resolve(vertical, uc)
        for k, pred in ((r or {}).get("requirements") or {}).items():
            if k in out:
                continue                       # legacy/stated/title already set it — don't override
            if isinstance(pred, (list, tuple)) and len(pred) == 2:
                out[k] = [(pred[0], pred[1])]   # registry [op, value] → decision [(op, value)]
    return out


def resolve(use_cases: Optional[List[str]],
            model_requirements: Optional[Dict[str, Any]] = None,
            query: Optional[str] = None,
            vertical: Optional[str] = None) -> Dict[str, Any]:
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
    resolved = _ordered_use_cases(resolved)

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
    primary_use_case = resolved[0] if resolved else None
    if primary_use_case:
        persona_hint = ((_kb().get("use_cases") or {}).get(primary_use_case) or {}).get("nqe_persona")

    # inject the registry's boolean/enum capability predicates AFTER the numeric projection
    # (they can't ride the constraint machinery); MERGE-not-override, so legacy/stated/title win.
    final_reqs = _inject_registry_capabilities(project(merged), resolved, vertical)
    return {"requirements": final_reqs, "constraints": as_dicts(merged),
            "conflicts": constraint_conflicts(merged), "use_cases": resolved,
            "profile_trace": profile_trace, "title_requirements": title["trace"],
            "persona_hint": persona_hint, "primary_use_case": primary_use_case}
