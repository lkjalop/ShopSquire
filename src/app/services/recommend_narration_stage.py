"""Narration input stage for the recommendation route.

The LLM narrator should describe evidence the system already has, not infer the
shopper intent again from raw text. This module converts QueryUnderstanding into
a small, traceable narration envelope used by both LLM and deterministic copy.
It is vertical-agnostic: it carries values, provenance, and assumptions only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.app.services.query_understanding import QueryUnderstanding, build_query_understanding


def run_narration(
    timing_breakdown: Dict[str, Any],
    *,
    mode: str,
    query: Any,
    results: Any,
    constraints: Any,
    summ_model: Any,
    trace_id: Any,
    combined_preamble: Any,
    narration_inputs: Any,
    summarize_fn: Callable[..., Tuple[Any, Any]],
    executor: Any = None,
    redis: Any = None,
    submit_fn: Optional[Callable[..., Any]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Tier-1 narration latency control. Returns (assistant_message, llm_summary_job_id) and writes
    narration_mode / summary_ms / narration_pending into ``timing_breakdown``.

    LLM narration was measured at 85-91% of route latency, so the mode is the latency lever:
      * ``blocking`` (default): call the LLM now (timed via StageTimer) -> prose.
      * ``skip``: no LLM call -> (None, None); the route's deterministic fallback fills the message.
      * ``async``: skip now + enqueue the prose as a background job (client polls /narration/{id}).
    ``summarize_fn`` is injected (the route's _summarize_results) so this is unit-testable without an
    LLM. Never raises on the async-enqueue path (job id -> None on failure)."""
    from src.app.observability.stage_timer import StageTimer

    m = str(mode or "blocking").strip().lower()
    if m not in ("blocking", "skip", "async"):
        m = "blocking"
    if isinstance(timing_breakdown, dict):
        timing_breakdown["narration_mode"] = m

    assistant_message: Optional[str] = None
    llm_summary_job_id: Optional[str] = None

    if m == "blocking":
        with StageTimer(timing_breakdown, "summary_ms"):  # time the dominant LLM cost
            assistant_message, llm_summary_job_id = summarize_fn(
                query, results, constraints, summ_model, trace_id,
                context_preamble=combined_preamble,
                narration_inputs=narration_inputs,
            )
        return assistant_message, llm_summary_job_id

    # skip / async: no blocking LLM call — the deterministic grounded message fills in downstream.
    if isinstance(timing_breakdown, dict):
        timing_breakdown["summary_ms"] = 0
        timing_breakdown["narration_pending"] = (m == "async")
    if m == "async":
        if submit_fn is None:
            try:
                from src.app.services.recommend_narration_jobs import submit_narration as submit_fn  # type: ignore
            except Exception:
                submit_fn = None
        if submit_fn is not None:
            try:
                llm_summary_job_id = submit_fn(
                    executor, redis, summarize_fn,
                    query, list(results or []), dict(constraints or {}), summ_model, trace_id,
                    context_preamble=combined_preamble, narration_inputs=narration_inputs,
                )
            except Exception:
                llm_summary_job_id = None
    return assistant_message, llm_summary_job_id


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
