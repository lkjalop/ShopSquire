"""Unified use-case registry (Track E consolidation) — ONE data-driven source per vertical.

Replaces the four drifting KB files with `data/use_cases/{vertical}.json` in the HYBRID namespace:
a COARSE use-case (`gaming`) carries a `baseline` spec + `budget_floor`, and optional fine
`variants` (`competitive`, `aaa_heavy`, …) that OVERRIDE the baseline (DRY). Mirrors
attribute_registry: vertical-blind mechanism, all knowledge in data, zero code per vertical.

STRANGLER: this is ADDITIVE. It stands beside the legacy KB files; consumers migrate onto
`resolve()` incrementally, then the legacy files are deleted. Nothing here changes what the
current recommender reads yet, so it does not perturb the V2 soak baseline.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("shopsquire.use_case_registry")

_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "use_cases"


@lru_cache(maxsize=16)
def load_use_cases(vertical: str) -> Dict[str, Any]:
    """The raw registry for one vertical, or {} when the file is absent (an un-scaffolded
    vertical resolves nothing rather than guessing)."""
    path = _DATA_DIR / f"{str(vertical).strip().lower()}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("use-case registry unreadable for %s: %s", vertical, exc)
        return {}


def list_use_cases(vertical: str) -> List[str]:
    return sorted((load_use_cases(vertical).get("use_cases") or {}).keys())


def list_variants(vertical: str, coarse: str) -> List[str]:
    uc = (load_use_cases(vertical).get("use_cases") or {}).get(str(coarse)) or {}
    return sorted((uc.get("variants") or {}).keys())


def resolve(vertical: str, coarse: str, variant: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A coarse use-case (+ optional variant) → the merged, resolved knowledge, or None when the
    coarse key is unknown. Merge rule: variant fields OVERRIDE the baseline; budget_floor is the
    variant's if it declares one, else the coarse floor. An unknown variant falls back to the
    coarse baseline (never invents specs)."""
    uc = (load_use_cases(vertical).get("use_cases") or {}).get(str(coarse))
    if not isinstance(uc, dict):
        return None
    specs: Dict[str, Any] = dict(uc.get("baseline") or {})
    budget_floor = uc.get("budget_floor")
    resolved_variant = None
    vmap = uc.get("variants") or {}
    if variant and str(variant) in vmap:
        resolved_variant = str(variant)
        vspec = vmap[resolved_variant] or {}
        for k, v in vspec.items():
            if k in ("note", "budget_floor"):
                continue
            specs[k] = v                                   # variant overrides baseline
        if vspec.get("budget_floor") is not None:
            budget_floor = vspec["budget_floor"]
    out: Dict[str, Any] = {
        "vertical": str(vertical), "use_case": str(coarse), "variant": resolved_variant,
        "label": uc.get("label"), "specs": specs, "budget_floor": budget_floor,
        "host_nodes": uc.get("host_nodes") or (load_use_cases(vertical).get("host_nodes") or []),
        "keywords": uc.get("keywords") or [],
    }
    if uc.get("content_advisory"):
        out["content_advisory"] = uc["content_advisory"]
    return out


def content_advisory(vertical: str, coarse: str) -> Optional[Dict[str, Any]]:
    """The advisory (if any) for a coarse use-case — e.g. a minor persona requesting mature-rated
    game specs. ADVISORY: the caller surfaces a clarification, never a hard block."""
    uc = (load_use_cases(vertical).get("use_cases") or {}).get(str(coarse)) or {}
    return uc.get("content_advisory")
