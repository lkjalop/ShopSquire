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
    true_markers: Tuple[str, ...] = ()   # boolean: phrases in title/specs that imply True
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
                true_markers=tuple(str(m).lower() for m in d.get("true_markers") or ()),
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


@lru_cache(maxsize=8)
def load_derivations(vertical: str) -> Tuple[Dict[str, Any], ...]:
    """Cross-key derivation rules for one vertical (review-8 #5). Each rule fills ONE target
    attribute from OTHER already-normalized attributes — e.g. gpu_discrete=false ⇒ gpu_vram_gb=0.
    A rule is kept only when its target and every `when` key name a REAL def for this vertical
    (a derivation over an unknown attribute is a data bug, dropped with a warning — never a guess).
    Shape: {target, set, when:{key:value,...}, only_if_missing:bool}."""
    defs = load_defs(vertical)
    if not defs:
        return ()
    path = _DATA_DIR / f"{str(vertical).strip().lower()}.json"
    out: List[Dict[str, Any]] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for r in (raw.get("derivations") or []):
            target = str(r.get("target") or "")
            when = r.get("when") or {}
            if target not in defs or not isinstance(when, dict) or not when:
                logger.warning("derivation over unknown/empty keys in %s — skipped: %r", vertical, r)
                continue
            if any(k not in defs for k in when):
                logger.warning("derivation `when` names an unknown key in %s — skipped: %r", vertical, r)
                continue
            out.append({"target": target, "set": r.get("set"),
                        "when": {str(k): v for k, v in when.items()},
                        "only_if_missing": bool(r.get("only_if_missing", True))})
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("derivations unreadable for %s: %s", vertical, exc)
    return tuple(out)


def derivations_union(verticals: Tuple[str, ...]) -> Tuple[Dict[str, Any], ...]:
    """Concatenated derivation rules across verticals, de-duplicated by (target, when)."""
    seen = set()
    merged: List[Dict[str, Any]] = []
    for v in verticals:
        for r in load_derivations(v):
            key = (r["target"], tuple(sorted((k, str(val)) for k, val in r["when"].items())))
            if key not in seen:
                seen.add(key)
                merged.append(r)
    return tuple(merged)


def apply_derivations(attrs: Dict[str, Any], derivations: Tuple[Dict[str, Any], ...],
                      defs: Dict[str, AttributeDef]) -> Dict[str, Any]:
    """Fill derivable target attributes IN PLACE from already-normalized attrs. Honesty rules,
    same as extraction: (1) `only_if_missing` never overrides structured catalog data;
    (2) a `when` key absent from attrs means NO evidence → the rule does not fire (we do not
    infer 'discrete' from the mere absence of gpu_discrete); (3) the derived value is clamped
    through the target def's normalizer — an out-of-bounds derived value is dropped, not stored."""
    for r in derivations or ():
        target = r["target"]
        if r["only_if_missing"] and target in attrs:
            continue
        when = r["when"]
        if any(k not in attrs or attrs[k] != v for k, v in when.items()):
            continue
        val = normalize_value(defs[target], r["set"]) if target in defs else None
        if val is not None:
            attrs[target] = val
    return attrs


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


def extract_keyed_quantity_requirements(
    text: str, defs: Dict[str, AttributeDef]
) -> Dict[str, List[Tuple[str, float]]]:
    """Bind explicit number+unit values to buyer-named registry attributes.

    Shared units such as GB are safe only when the buyer also names the key, for example
    ``16GB RAM`` or ``VRAM 8GB``. Attribute vocabulary, unit conversion and bounds come from
    registry data, keeping this clamp vertical-blind.
    """
    query = str(text or "")
    out: Dict[str, List[Tuple[str, float]]] = {}
    ceiling = re.compile(
        r"\b(at\s+most|maximum|max\.?|up\s+to|no\s+more\s+than|or\s+less|or\s+lower)\b", re.I
    )
    for key, definition in defs.items():
        if definition.kind != "quantity" or not definition.text_extract:
            continue
        aliases = sorted({key, *definition.key_aliases}, key=len, reverse=True)
        units = sorted({*(definition.unit_aliases or {}), (definition.unit or "").lower()} - {""},
                       key=len, reverse=True)
        if not aliases or not units:
            continue
        alias_pat = "|".join(re.escape(value) for value in aliases)
        unit_pat = "|".join(re.escape(value) for value in units)
        number = r"([0-9]+(?:\.[0-9]+)?)"
        patterns = (
            re.compile(rf"{number}\s*({unit_pat})\s*(?:of\s+)?(?:{alias_pat})\b", re.I),
            re.compile(
                rf"\b(?:{alias_pat})\b\s*"
                rf"(?:of|at\s+least|at\s+most|minimum|maximum|up\s+to|is|:)?\s*"
                rf"{number}\s*({unit_pat})\b", re.I
            ),
        )
        for pattern in patterns:
            for match in pattern.finditer(query):
                value = normalize_value(definition, f"{match.group(1)}{match.group(2)}")
                if value is None:
                    continue
                context = query[max(0, match.start() - 28):min(len(query), match.end() + 28)]
                predicate = ("<=" if ceiling.search(context) else ">=", float(value))
                if predicate not in out.setdefault(key, []):
                    out[key].append(predicate)
    return out


def extract_categoricals(text: str, defs: Dict[str, AttributeDef]) -> Dict[str, Any]:
    """ENUM + BOOLEAN attributes read from free text (the product TITLE) — the capability signals
    that make the platform SMART about form-factor / touch / stylus without structured specs. A
    laptop titled 'HP Envy x360 2-in-1' yields form_factor='convertible' + touchscreen=True from the
    declared aliases/true_markers; a title with no marker yields nothing (never a guess). Word/
    phrase-boundary matched so 'yoga' in 'Yoga Slim' matches but not inside another word."""
    low = f" {str(text or '').lower()} "
    out: Dict[str, Any] = {}
    for key, d in defs.items():
        if not d.text_extract or d.kind not in ("enum", "boolean"):
            continue
        if d.kind == "enum":
            for canonical, aliases in d.enum_values.items():
                if any(_phrase_in(low, a) for a in aliases) or _phrase_in(low, canonical.lower()):
                    out[key] = canonical           # first canonical whose alias appears wins
                    break
        else:  # boolean
            if any(_phrase_in(low, m) for m in d.true_markers):
                out[key] = True                    # only POSITIVE markers assert; absence ≠ False
    return out


def _phrase_in(haystack_padded: str, needle: str) -> bool:
    """Whitespace/boundary-aware substring: 'x360' matches 'x360' as a token; a hyphen/space in the
    needle ('2-in-1') is matched literally; short alnum needles require a boundary to avoid
    'go' matching 'good'."""
    n = str(needle or "").strip().lower()
    if not n:
        return False
    if n in haystack_padded:
        # accept if bounded by non-alnum on both sides (padded string has leading/trailing spaces)
        i = haystack_padded.find(n)
        left = haystack_padded[i - 1] if i > 0 else " "
        right = haystack_padded[i + len(n)] if i + len(n) < len(haystack_padded) else " "
        return not (left.isalnum() or right.isalnum())
    return False


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
