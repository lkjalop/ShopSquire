"""LangGraph-compatible typed state for orchestrator phases.

Provides a TypedDict-based state schema replacing ad-hoc dict passing between
orchestrator phases.  Each phase reads its inputs and writes its outputs
through a single ``PipelineState`` object.

Compatible with LangGraph's ``StateGraph`` protocol:
  - ``PipelineState`` inherits from ``TypedDict``
  - Keys are optional (NotRequired) so phases can run incrementally
  - ``merge_phase_output()`` safely overlays partial updates

Usage in the orchestrator::

    from src.app.services.pipeline_state import PipelineState, merge_phase_output

    state: PipelineState = init_pipeline_state(trace_id, uid, payload)
    state = merge_phase_output(state, {"nlp_slots": parsed_slots})
    # ...pass state through phases
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

try:
    from typing import NotRequired, TypedDict
except ImportError:
    from typing_extensions import NotRequired, TypedDict


# ---------------------------------------------------------------------------
# Phase-specific typed dicts
# ---------------------------------------------------------------------------

class NLPSlots(TypedDict, total=False):
    intent: str
    product_category: Optional[str]
    constraints: Dict[str, Any]
    negations: List[str]
    budget_min: Optional[float]
    budget_max: Optional[float]
    brand_preference: Optional[str]
    query_text: str


class CandidateProduct(TypedDict, total=False):
    product_id: str
    name: str
    score: float
    specs: Dict[str, Any]
    price: Optional[float]


class RankingResult(TypedDict, total=False):
    ranked_products: List[CandidateProduct]
    ranking_method: str
    diversity_score: float
    why_explanations: Dict[str, str]
    delta_vs_anchor: Dict[str, Dict[str, str]]


class FraudResult(TypedDict, total=False):
    fraud_score: float
    fraud_signals: Dict[str, float]
    risk_level: str
    biometric_risk: float
    gnn_risk: float


class SecurityResult(TypedDict, total=False):
    threat_detected: bool
    vuln_findings: List[Dict[str, Any]]
    bec_indicators: Dict[str, Any]
    thread_hijack: Dict[str, Any]
    incidents_created: List[Dict[str, str]]


class DebateResult(TypedDict, total=False):
    debate_ran: bool
    scenario: str
    verdict: str
    judge_escalated: bool
    confidence: float


class SelfReflection(TypedDict, total=False):
    query_responded: bool
    issues: List[str]


# ---------------------------------------------------------------------------
# Main pipeline state
# ---------------------------------------------------------------------------

class PipelineState(TypedDict, total=False):
    # Metadata
    trace_id: str
    uid: str
    tenant_id: Optional[str]
    timestamp: float
    phase: str

    # Phase 1: NLP + retrieval
    raw_payload: Dict[str, Any]
    nlp_slots: NLPSlots
    retrieved_context: Dict[str, Any]
    nqe_questions: List[Dict[str, str]]
    nqe_converged: bool

    # Phase 2: Candidates
    candidates: List[CandidateProduct]
    candidate_count: int

    # Phase 3: Ranking
    ranking: RankingResult

    # Phase 3b: Debate
    debate: DebateResult

    # Phase 4: Security / fraud
    fraud: FraudResult
    security: SecurityResult

    # Post-processing
    self_reflection: SelfReflection
    guardrail_actions: List[str]
    proposal: Dict[str, Any]

    # Timings
    timings: Dict[str, float]
    errors: List[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def init_pipeline_state(
    trace_id: str,
    uid: str,
    payload: Dict[str, Any],
    *,
    tenant_id: Optional[str] = None,
) -> PipelineState:
    """Create an initial pipeline state from the inbound payload."""
    return PipelineState(
        trace_id=trace_id,
        uid=uid,
        tenant_id=tenant_id,
        timestamp=time.time(),
        phase="init",
        raw_payload=payload,
        timings={},
        errors=[],
    )


def merge_phase_output(state: PipelineState, updates: Dict[str, Any]) -> PipelineState:
    """Merge partial phase outputs into the pipeline state.

    Returns a new dict (does not mutate the input).
    """
    merged = dict(state)
    for k, v in updates.items():
        if k == "timings" and isinstance(v, dict) and isinstance(merged.get("timings"), dict):
            merged["timings"] = {**merged["timings"], **v}
        elif k == "errors" and isinstance(v, list) and isinstance(merged.get("errors"), list):
            merged["errors"] = merged["errors"] + v
        else:
            merged[k] = v
    return PipelineState(**merged)  # type: ignore[misc]


def phase_summary(state: PipelineState) -> Dict[str, Any]:
    """Return a compact summary of the state for tracing / logging."""
    return {
        "trace_id": state.get("trace_id"),
        "phase": state.get("phase"),
        "candidate_count": state.get("candidate_count", 0),
        "nqe_converged": state.get("nqe_converged", False),
        "fraud_score": (state.get("fraud") or {}).get("fraud_score"),
        "debate_ran": (state.get("debate") or {}).get("debate_ran", False),
        "self_reflection_ok": (state.get("self_reflection") or {}).get("query_responded"),
        "error_count": len(state.get("errors") or []),
        "timing_phases": sorted((state.get("timings") or {}).keys()),
    }
