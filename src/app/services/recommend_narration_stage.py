"""Narration input stage for the recommendation route.

The LLM narrator should describe evidence the system already has, not infer the
shopper intent again from raw text. This module converts QueryUnderstanding into
a small, traceable narration envelope used by both LLM and deterministic copy.
It is vertical-agnostic: it carries values, provenance, and assumptions only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.services.query_understanding import QueryUnderstanding, build_query_understanding


@dataclass(frozen=True)
class NarrationInputs:
    query_text: str
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    budget_text: str = ""
    use_case: str = ""
    buyer_persona: str = ""
    brands: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    assumptions: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_text": self.query_text,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "budget_text": self.budget_text,
            "use_case": self.use_case,
            "buyer_persona": self.buyer_persona,
            "brands": list(self.brands),
            "missing": list(self.missing),
            "assumptions": list(self.assumptions),
            "provenance": dict(self.provenance),
        }


def _num(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value or "").replace(",", "").replace("$", "").strip()
        return float(text) if text else None
    except Exception:
        return None


def _budget_text(budget_min: Optional[float], budget_max: Optional[float]) -> str:
    if budget_min is not None and budget_max is not None:
        return f"${int(budget_min):,}-${int(budget_max):,}"
    if budget_max is not None:
        return f"under ${int(budget_max):,}"
    if budget_min is not None:
        return f"above ${int(budget_min):,}"
    return ""


def build_narration_inputs(
    query: str | None,
    constraints: Dict[str, Any] | None,
    *,
    query_understanding: QueryUnderstanding | None = None,
) -> NarrationInputs:
    c = dict(constraints or {})
    qu = query_understanding or build_query_understanding(str(query or ""), c)

    budget_min = qu.budget_min if qu.budget_min is not None else _num(c.get("budget_min"))
    budget_max = qu.budget_max if qu.budget_max is not None else _num(c.get("budget_max"))
    use_case = str(qu.use_case or c.get("use_case") or "").strip()
    brands = list(qu.brands or [])
    if not brands:
        raw_brands = c.get("brands") or c.get("brand_hints") or []
        brands = [str(b).strip().lower() for b in raw_brands if str(b).strip()] if isinstance(raw_brands, list) else []
    shopper_intent = c.get("shopper_intent") if isinstance(c.get("shopper_intent"), dict) else {}
    buyer_persona = str(
        c.get("buyer_persona")
        or c.get("inferred_persona")
        or shopper_intent.get("persona")
        or ""
    ).strip()

    return NarrationInputs(
        query_text=str(query or qu.query_text or ""),
        budget_min=budget_min,
        budget_max=budget_max,
        budget_text=_budget_text(budget_min, budget_max),
        use_case=use_case,
        buyer_persona=buyer_persona,
        brands=brands,
        missing=list(qu.missing or []),
        assumptions=list(qu.assumptions or []),
        provenance=dict(qu.provenance or {}),
    )


def apply_narration_inputs_to_constraints(
    constraints: Dict[str, Any] | None,
    narration: NarrationInputs,
) -> Dict[str, Any]:
    """Return a copy of constraints with QueryUnderstanding-backed narration fields filled."""
    out = dict(constraints or {})
    if narration.budget_min is not None and out.get("budget_min") is None:
        out["budget_min"] = narration.budget_min
    if narration.budget_max is not None and out.get("budget_max") is None:
        out["budget_max"] = narration.budget_max
    if narration.use_case and not out.get("use_case"):
        out["use_case"] = narration.use_case
    if narration.brands and not out.get("brands"):
        out["brands"] = list(narration.brands)
    out["_query_understanding"] = narration.to_dict()
    return out


def build_narration_evidence_block(narration: NarrationInputs) -> str:
    """Compact prompt block: what the narrator may rely on, with provenance."""
    lines: list[str] = ["Structured interpretation evidence:"]
    if narration.budget_text:
        src = narration.provenance.get("budget_max") or narration.provenance.get("budget_min") or "unknown"
        lines.append(f"- Budget: {narration.budget_text} (source: {src})")
    if narration.use_case:
        src = narration.provenance.get("use_case") or "unknown"
        lines.append(f"- Use case: {narration.use_case.replace('_', ' ')} (source: {src})")
    if narration.brands:
        src = narration.provenance.get("brands") or "unknown"
        lines.append(f"- Brand preference: {', '.join(narration.brands[:4])} (source: {src})")
    if narration.assumptions:
        rendered = []
        for item in narration.assumptions[:4]:
            if isinstance(item, dict) and item.get("field"):
                rendered.append(f"{item.get('field')}={item.get('value')} ({item.get('basis')})")
        if rendered:
            lines.append("- Overridable assumptions: " + "; ".join(rendered))
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
