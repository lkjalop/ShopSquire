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


def _profile_requirements(use_case: str) -> Dict[str, Tuple[str, float]]:
    """One use-case's required_specs → {attr_key: (op, threshold)}."""
    specs = ((_kb().get("use_cases") or {}).get(use_case) or {}).get("required_specs") or {}
    out: Dict[str, Tuple[str, float]] = {}
    for spec_key, val in specs.items():
        if spec_key in _SPEC_MAP and isinstance(val, (int, float)):
            attr, op = _SPEC_MAP[spec_key]
            out[attr] = (op, float(val))
        elif spec_key == "gpu_tier" and str(val) in _GPU_TIER_VRAM:
            out["gpu_vram_gb"] = (">=", float(_GPU_TIER_VRAM[str(val)]))
    return out


def _merge_max(a: Dict[str, Tuple[str, float]],
               b: Dict[str, Tuple[str, float]]) -> Dict[str, Tuple[str, float]]:
    """Merge two requirement maps by MAX threshold per key (most demanding wins — the safe
    recommendation; a machine meeting the stricter floor meets both)."""
    out = dict(a)
    for k, (op, thr) in b.items():
        if k not in out:
            out[k] = (op, thr)
        else:
            out[k] = (op, max(out[k][1], thr))   # same op family (all >=); take the higher floor
    return out


def resolve(use_cases: Optional[List[str]],
            model_requirements: Optional[Dict[str, Tuple[str, float]]] = None
            ) -> Dict[str, Any]:
    """The resolver. Returns:
      requirements  — merged (KB profiles ∪ model-stated) by MAX; the fit stage consumes it.
      use_cases     — the resolved (normalized, real) use-case keys.
      profile_trace — per-use-case requirement contribution (for the 'Why Recommended' tab).
      persona_hint  — the primary use-case's nqe_persona (drives the use-case-specific clarify).
    Multi-intent falls out naturally: pass ['gaming','creative'] → the union by MAX."""
    resolved: List[str] = []
    for uc in (use_cases or []):
        n = normalize_use_case(uc)
        if n and n not in resolved:
            resolved.append(n)

    merged: Dict[str, Tuple[str, float]] = {}
    profile_trace: Dict[str, Dict[str, Any]] = {}
    for uc in resolved:
        prof = _profile_requirements(uc)
        profile_trace[uc] = {"requirements": {k: [op, thr] for k, (op, thr) in prof.items()},
                             "label": ((_kb().get("use_cases") or {}).get(uc) or {}).get("label", uc)}
        merged = _merge_max(merged, prof)
    # the model's explicitly-stated requirements ('144fps') merge in, MAX again
    if model_requirements:
        merged = _merge_max(merged, dict(model_requirements))

    persona_hint = None
    if resolved:
        persona_hint = ((_kb().get("use_cases") or {}).get(resolved[0]) or {}).get("nqe_persona")

    return {"requirements": merged, "use_cases": resolved,
            "profile_trace": profile_trace, "persona_hint": persona_hint}
