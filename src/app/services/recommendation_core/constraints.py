"""Requirement constraints as RANGES with provenance (M2-B1 — GPT-5.6 review-4 Q1/review-5 B1).

The `(op, threshold)` one-slot cannot hold a floor AND a ceiling: 'a laptop with at least 16GB'
(KB floor) plus 'nothing over 32GB' (stated ceiling) is ONE range, 16 ≤ ram ≤ 32 — but a
single-slot merge must throw one bound away, and the old incoming-wins rule silently dropped
whichever arrived first. Worse, floor>ceiling ('nothing over 8GB' vs university floor 16) is a
CONFLICT the shopper must resolve — not something any silent rule may decide.

This module is the fix, and the doctrine is the platform's:
  model/KB PROPOSE bounds (each with provenance) → deterministic INTERSECTION merges them →
  a conflict is SURFACED (clarify), never silently resolved → the fit stage evaluates the
  full range (a predicate per bound), tri-state as ever.

Vertical-blind: keys are attribute-registry keys; nothing here knows RAM from milligrams."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

# the closed op vocabulary shared with turn_router/attribute_registry
_LOWER_OPS = (">=", ">")
_UPPER_OPS = ("<=", "<")


@dataclass(frozen=True)
class RequirementConstraint:
    """One attribute's merged requirement: [lower, upper] with strictness, an optional
    preferred value (KB 'recommended'), and the provenance of every bound that contributed.
    NOTE (review-6 #20): `preferred` is RECORDED but NOT yet consumed by ranking — a single
    value is kept (first-wins) and no ranker reads it. Wiring `preferred` into the ranker (as a
    soft nearness signal, clamped into [lower, upper]) is a tracked follow-up; until then it is
    trace/telemetry only, never elimination."""
    key: str
    lower: Optional[float] = None
    upper: Optional[float] = None
    lower_strict: bool = False        # True ⇔ '>' rather than '>='
    upper_strict: bool = False        # True ⇔ '<' rather than '<='
    preferred: Optional[float] = None
    provenance: Tuple[str, ...] = ()

    @property
    def is_conflict(self) -> bool:
        """Empty range: lower > upper, or lower == upper with a strict edge."""
        if self.lower is None or self.upper is None:
            return False
        if self.lower > self.upper:
            return True
        return self.lower == self.upper and (self.lower_strict or self.upper_strict)

    def predicates(self) -> List[Tuple[str, float]]:
        """The (op, threshold) list the tri-state evaluator consumes — 0, 1, or 2 entries.
        A conflicted constraint yields NO predicates: contradictory info must not gate."""
        if self.is_conflict:
            return []
        out: List[Tuple[str, float]] = []
        if self.lower is not None:
            out.append((">" if self.lower_strict else ">=", self.lower))
        if self.upper is not None:
            out.append(("<" if self.upper_strict else "<=", self.upper))
        return out

    def describe(self) -> str:
        lo = f"{'>' if self.lower_strict else '≥'}{self.lower:g}" if self.lower is not None else ""
        hi = f"{'<' if self.upper_strict else '≤'}{self.upper:g}" if self.upper is not None else ""
        body = " and ".join(b for b in (lo, hi) if b) or "any"
        return f"{self.key} {body}" + (" (CONFLICT)" if self.is_conflict else "")

    def as_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "lower": self.lower, "upper": self.upper,
                "lower_strict": self.lower_strict, "upper_strict": self.upper_strict,
                "preferred": self.preferred, "provenance": list(self.provenance),
                "conflict": self.is_conflict}


def from_op(key: str, op: str, value: float, source: str) -> RequirementConstraint:
    """Normalize one (op, value) bound to a range. '==' pins both bounds."""
    v = float(value)
    if op in _LOWER_OPS:
        return RequirementConstraint(key=key, lower=v, lower_strict=(op == ">"),
                                     provenance=(source,))
    if op in _UPPER_OPS:
        return RequirementConstraint(key=key, upper=v, upper_strict=(op == "<"),
                                     provenance=(source,))
    if op == "==":
        return RequirementConstraint(key=key, lower=v, upper=v, provenance=(source,))
    raise ValueError(f"unknown op {op!r} for {key}")


def merge(a: RequirementConstraint, b: RequirementConstraint) -> RequirementConstraint:
    """INTERSECTION: the tightest range satisfying both. floor+floor→max, ceiling+ceiling→min,
    floor+ceiling→range. A resulting empty range reads as is_conflict — SURFACED, never
    silently resolved in either party's favour (the 'nothing over 8GB' inversion class)."""
    if a.key != b.key:
        raise ValueError(f"cannot merge {a.key} with {b.key}")
    # lower: the HIGHER floor wins; on a tie, strict wins (tighter)
    if a.lower is None or (b.lower is not None and (b.lower > a.lower or
                                                    (b.lower == a.lower and b.lower_strict))):
        lower, lower_strict = b.lower, b.lower_strict
    else:
        lower, lower_strict = a.lower, a.lower_strict
    # upper: the LOWER ceiling wins; on a tie, strict wins (tighter)
    if a.upper is None or (b.upper is not None and (b.upper < a.upper or
                                                    (b.upper == a.upper and b.upper_strict))):
        upper, upper_strict = b.upper, b.upper_strict
    else:
        upper, upper_strict = a.upper, a.upper_strict
    preferred = a.preferred if a.preferred is not None else b.preferred
    return RequirementConstraint(key=a.key, lower=lower, upper=upper,
                                 lower_strict=lower_strict, upper_strict=upper_strict,
                                 preferred=preferred,
                                 provenance=tuple(dict.fromkeys(a.provenance + b.provenance)))


# ── map-level helpers (the shapes the resolver pipeline moves around) ────────────

ConstraintMap = Dict[str, RequirementConstraint]


def from_op_map(op_map: Dict[str, Any], source: str) -> ConstraintMap:
    """{key: (op, thr)} or {key: [(op, thr), ...]} → ConstraintMap (each bound provenance-tagged)."""
    out: ConstraintMap = {}
    for key, spec in (op_map or {}).items():
        preds = spec if isinstance(spec, list) else [spec]
        for op, thr in preds:
            c = from_op(key, str(op), float(thr), source)
            out[key] = merge(out[key], c) if key in out else c
    return out


def merge_maps(*maps: ConstraintMap) -> ConstraintMap:
    """Intersection-merge any number of constraint maps."""
    out: ConstraintMap = {}
    for m in maps:
        for key, c in (m or {}).items():
            out[key] = merge(out[key], c) if key in out else c
    return out


def project(cs: ConstraintMap) -> Dict[str, List[Tuple[str, float]]]:
    """ConstraintMap → {key: [(op, thr), ...]} for evaluate_requirements. Conflicted keys
    project to NOTHING (contradictory info must not gate a product in or out)."""
    return {k: c.predicates() for k, c in (cs or {}).items() if not c.is_conflict}


def conflicts(cs: ConstraintMap) -> List[Dict[str, Any]]:
    """The surfaced-conflict list (clarify material): every key whose merged range is empty."""
    return [c.as_dict() for c in (cs or {}).values() if c.is_conflict]


def as_dicts(cs: ConstraintMap) -> Dict[str, Dict[str, Any]]:
    return {k: c.as_dict() for k, c in (cs or {}).items()}
