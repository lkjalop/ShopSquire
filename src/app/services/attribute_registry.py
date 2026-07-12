"""Attribute normalization layer (V2 Phase 3.5) — the fit half of grounding.

Category grounding (taxonomy_registry) answers "do we sell this KIND of thing?". THIS layer
answers the other half GPT-5.6 named as the largest gap: "is THIS product suitable for this
buyer's workload/budget/constraints?" — by turning free-form spec soup into canonical, typed,
unit-normalized, bounds-clamped attributes that a deterministic comparator can evaluate.

VERTICAL-BLIND BY CONSTRUCTION: every definition — canonical keys, roles, kinds, units, unit
multipliers, key aliases, enum vocabularies, sanity bounds — lives in data
(data/attributes/{vertical}.json). RAM-in-GB and dosage-in-mg are the same mechanism; a new
vertical is a new JSON file, zero code.

HONESTY RULES (each one closes a recorded failure class):
  • Never guess: an unparseable value, unknown enum member, or out-of-bounds quantity is
    DROPPED WITH A REASON, never coerced (the live catalog has ram_gb=512 — storage stuffed
    into the RAM field; bounds catch it instead of recommending a 512GB-RAM laptop).
  • Ambiguity is surfaced, not resolved by luck: free-text extraction is anchored on UNIT
    grammar only (240Hz, 500ml, SPF50 are closed grammar — safe). A unit shared by several
    keys (GB: ram/vram/storage) is collected under `ambiguous` and NEVER assigned — key
    assignment for ambiguous units is model work (clamped to these defs), not regex work.
  • Comparison is tri-state: meets() returns None when the attribute is missing/unparsed —
    "unknown" must never silently count as pass OR fail (the workload stage decides how to
    present unknowns; it must not be lied to).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("shopsquire.attribute_registry")

_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "attributes"

ROLES = ("variant_axis", "descriptive", "fit", "regulatory", "offer")
KINDS = ("quantity", "enum", "boolean", "text")


@dataclass(frozen=True)
class AttributeDef:
    key: str
    vertical: str
    role: str
    kind: str
    unit: Optional[str] = None
    bounds: Optional[Tuple[float, float]] = None
    key_aliases: Tuple[str, ...] = ()
    unit_aliases: Dict[str, float] = field(default_factory=dict)   # alias -> multiplier to canonical
    enum_values: Dict[str, Tuple[str, ...]] = field(default_factory=dict)  # canonical -> aliases
    text_extract: bool = False


@lru_cache(maxsize=8)
def load_defs(vertical: str) -> Dict[str, AttributeDef]:
    """Definitions for one vertical, keyed by canonical attribute key. Empty dict when the
    vertical has no file — an ungrounded vertical normalizes nothing rather than guessing."""
    path = _DATA_DIR / f"{str(vertical).strip().lower()}.json"
    out: Dict[str, AttributeDef] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key, d in (raw.get("attributes") or {}).items():
            role = str(d.get("role") or "descriptive")
            kind = str(d.get("kind") or "text")
            if role not in ROLES or kind not in KINDS:
                logger.warning("attribute def %s/%s has invalid role/kind — skipped", vertical, key)
                continue
            bounds = d.get("bounds")
            out[key] = AttributeDef(
                key=key, vertical=str(raw.get("vertical") or vertical), role=role, kind=kind,
                unit=d.get("unit"),
                bounds=(float(bounds[0]), float(bounds[1])) if bounds else None,
                key_aliases=tuple(str(a).lower() for a in d.get("key_aliases") or ()),
                unit_aliases={str(k).lower(): float(v) for k, v in (d.get("unit_aliases") or {}).items()},
                enum_values={str(c): tuple(str(a).lower() for a in al)
                             for c, al in (d.get("values") or {}).items()},
                text_extract=bool(d.get("text_extract")),
            )
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("attribute defs unreadable for %s: %s", vertical, exc)
    return out


def defs_union(verticals: Tuple[str, ...]) -> Dict[str, AttributeDef]:
    """Merged defs for a multi-vertical catalog (first vertical wins a key collision)."""
    merged: Dict[str, AttributeDef] = {}
    for v in verticals:
        for k, d in load_defs(v).items():
            merged.setdefault(k, d)
    return merged


def _key_index(defs: Dict[str, AttributeDef]) -> Dict[str, str]:
    idx: Dict[str, str] = {}
    for key, d in defs.items():
        idx[key.lower()] = key
        for a in d.key_aliases:
            idx.setdefault(a, key)
    return idx


_NUM_RE = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([a-z%\"']*)\s*$", re.IGNORECASE)
_TRUE = frozenset({"true", "yes", "y", "1"})
_FALSE = frozenset({"false", "no", "n", "0"})


def normalize_value(d: AttributeDef, raw: Any) -> Optional[Any]:
    """One value → canonical form, or None (never a guess).
    quantity: number or 'number[unit]' string, unit-converted + bounds-clamped.
    enum: canonical name or declared alias, case-insensitive. boolean: common literals."""
    if raw is None:
        return None
    if d.kind == "quantity":
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            val = float(raw)
        else:
            m = _NUM_RE.match(str(raw))
            if not m:
                return None
            val = float(m.group(1).replace(",", "."))
            unit = m.group(2).lower()
            if unit:
                if unit not in d.unit_aliases and unit != (d.unit or "").lower():
                    return None  # a unit we don't know is a value we don't trust
                val *= d.unit_aliases.get(unit, 1.0)
        if d.bounds and not (d.bounds[0] <= val <= d.bounds[1]):
            return None
        return round(val, 4)
    if d.kind == "enum":
        s = str(raw).strip().lower()
        for canonical, aliases in d.enum_values.items():
            if s == canonical.lower() or s in aliases:
                return canonical
        return None
    if d.kind == "boolean":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        return True if s in _TRUE else False if s in _FALSE else None
    text = str(raw).strip()
    return text or None


def normalize_specs(specs: Dict[str, Any], defs: Dict[str, AttributeDef]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """A raw spec dict → (canonical attributes, dropped-with-reason). Alias keys map to
    canonical keys; unknown keys pass through untouched under their own name is WRONG — they
    are reported as 'unknown_key' so schema drift is visible, never silently absorbed."""
    idx = _key_index(defs)
    out: Dict[str, Any] = {}
    dropped: List[Dict[str, Any]] = []
    for k, raw in (specs or {}).items():
        canon = idx.get(str(k).strip().lower())
        if canon is None:
            dropped.append({"key": k, "raw": raw, "reason": "unknown_key"})
            continue
        val = normalize_value(defs[canon], raw)
        if val is None:
            dropped.append({"key": k, "raw": raw, "reason": "unparseable_or_out_of_bounds",
                            "canonical": canon})
            continue
        out[canon] = val
    return out, dropped


def extract_quantities(text: str, defs: Dict[str, AttributeDef]) -> Tuple[Dict[str, float], Dict[str, List[float]]]:
    """Unit-anchored quantity extraction from free text ('27\" FHD 240Hz', 'SPF50+', '500ml').
    ONLY defs with text_extract=true participate; the pattern is built from the DECLARED unit
    grammar, never from product words. A unit claimed by >1 key (GB → ram/vram/storage) yields
    `ambiguous[unit] = [values]` — assignment there is the model's job, not this function's."""
    unit_to_keys: Dict[str, List[str]] = {}
    for key, d in defs.items():
        if d.kind != "quantity" or not d.text_extract:
            continue
        for u in list(d.unit_aliases) + ([d.unit.lower()] if d.unit else []):
            unit_to_keys.setdefault(u, [])
            if key not in unit_to_keys[u]:
                unit_to_keys[u].append(key)
    assigned: Dict[str, float] = {}
    ambiguous: Dict[str, List[float]] = {}
    if not unit_to_keys:
        return assigned, ambiguous
    units = sorted(unit_to_keys, key=len, reverse=True)
    pat = re.compile(r"(?:(spf)\s*([0-9]{1,3})|([0-9]+(?:\.[0-9]+)?)\s*(" +
                     "|".join(re.escape(u) for u in units if u != "spf") + r")(?![a-z0-9]))",
                     re.IGNORECASE)
    for m in pat.finditer(str(text or "")):
        if m.group(1):  # SPF prefix form
            unit, val = "spf", float(m.group(2))
        else:
            val, unit = float(m.group(3)), m.group(4).lower()
        keys = unit_to_keys.get(unit, [])
        if not keys:
            continue
        if len(keys) > 1:
            ambiguous.setdefault(unit, []).append(val)
            continue
        d = defs[keys[0]]
        canon_val = val * d.unit_aliases.get(unit, 1.0)
        if d.bounds and not (d.bounds[0] <= canon_val <= d.bounds[1]):
            continue
        # keep the MAX per key: '120Hz ... up to 165Hz' should read as the panel's capability
        assigned[keys[0]] = max(assigned.get(keys[0], 0.0), round(canon_val, 4))
    return assigned, ambiguous


# ── tri-state requirement evaluation (what the Phase-4 fit stage consumes) ────

_OPS = {
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
    "<": lambda a, b: a < b, "==": lambda a, b: a == b,
    "in": lambda a, b: a in (b if isinstance(b, (list, tuple, set)) else [b]),
}


def meets(attrs: Dict[str, Any], key: str, op: str, threshold: Any) -> Optional[bool]:
    """Tri-state: True/False when the attribute is present and comparable; None when missing
    or incomparable — UNKNOWN must never silently pass or fail a requirement."""
    if key not in (attrs or {}) or op not in _OPS:
        return None
    try:
        return bool(_OPS[op](attrs[key], threshold))
    except TypeError:
        return None


def _meets_all(attrs: Dict[str, Any], key: str, preds) -> Optional[bool]:
    """Tri-state over a predicate LIST (a range = floor + ceiling — M2-B1): False if any bound
    fails, None if none fail but one is unknowable, True only when every bound holds."""
    results = [meets(attrs, key, op, thr) for op, thr in preds]
    if any(r is False for r in results):
        return False
    if any(r is None for r in results):
        return None
    return True if results else None


def evaluate_requirements(attrs: Dict[str, Any],
                          requirements: Dict[str, Any]) -> Dict[str, Any]:
    """{key: (op, threshold)} OR {key: [(op, thr), ...]} (a RANGE, M2-B1) → per-key tri-state +
    an overall verdict: 'fails' if anything is False; 'unknown' if nothing fails but something
    is None; 'meets' only when every requirement is affirmatively True."""
    per_key: Dict[str, Optional[bool]] = {}
    for k, spec in (requirements or {}).items():
        preds = spec if isinstance(spec, list) else [spec]
        per_key[k] = _meets_all(attrs, k, preds)
    if any(v is False for v in per_key.values()):
        overall = "fails"
    elif any(v is None for v in per_key.values()):
        overall = "unknown"
    else:
        overall = "meets" if per_key else "unknown"
    return {"per_key": per_key, "overall": overall,
            "unknown_keys": sorted(k for k, v in per_key.items() if v is None)}
