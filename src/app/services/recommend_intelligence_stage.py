"""Recommend intelligence stage (agnostic CORE) — the three post-results intelligence blocks as ONE
tested unit, extracted from suggest():

  1. E0 attribution capture     — record which SKUs this decision proposed (for later attribution).
  2. Market-intelligence inject  — hippograph recall + gated market findings onto the response/session.
  3. Reversible ranking nudge    — treatment-only, experiment-gated, bounded boost to recalled products.

Each is independently flag-gated and fire-and-forget: every block runs in its own DB session and NEVER
blocks or breaks the response; failures are OBSERVED via record_partial_failure, not swallowed. The
stage mutates ``state.payload``/``state.kv`` in place and returns the (possibly nudged) results list.
Vertical-blind.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.app.services.decision_log import log_trace_event
from src.app.services.safe_stage import record_partial_failure


@dataclass
class IntelligenceStageState:
    results: List[Dict[str, Any]]
    payload: Dict[str, Any]
    flags: Dict[str, Any]
    simulate: bool
    uid: str
    uid_hash: Optional[str]
    query: Optional[str]
    constraints: Dict[str, Any]
    kv: Any
    proposal: Dict[str, Any]
    trace_id: Optional[str]
    decision_id: Optional[str]


def _capture(state: IntelligenceStageState, results: List[Dict[str, Any]]) -> None:
    if not (state.flags.get("ATTRIBUTION_ENABLED", True) and not state.simulate):
        return
    try:
        from src.app.models.db import db_session
        from src.app.services.attribution import record_decision
        from src.app.services.bandit_context import get_bandit_arm
        skus = [r.get("sku") for r in results if isinstance(r, dict) and r.get("sku")]
        # arm = the LinUCB ranking arm (for the E3 reward), variant = the A/B arm — distinct.
        with db_session() as db:
            record_decision(db, trace_id=state.trace_id, decision_id=state.decision_id, uid_hash=state.uid_hash,
                            skus=skus, surface="recommend", arm=get_bandit_arm(),
                            variant=(state.proposal or {}).get("ab_variant"),
                            context={"budget_max": state.constraints.get("budget_max"),
                                     "use_case": state.constraints.get("use_case")})
            db.commit()
    except Exception as exc:
        record_partial_failure("attribution_capture", exc, trace_id=state.trace_id)


def _market_intelligence(state: IntelligenceStageState, results: List[Dict[str, Any]], *, mem) -> None:
    if not (state.flags.get("HIPPOGRAPH_FEEDBACK_ENABLED", False) and not state.simulate):
        return
    try:
        from src.app.models.db import db_session
        from src.app.services.market_intelligence_agent import gather_market_context
        seed = [r.get("sku") for r in results if isinstance(r, dict) and r.get("sku")][:5]
        with db_session() as db:
            mi = gather_market_context(db, query=state.query, uid_hash=state.uid_hash, result_skus=seed, top_k=8)
        insights = mi.get("hippograph_insights") or []
        findings = mi.get("market_findings") or []
        evidence = mi.get("market_evidence") or {}
        note = mi.get("narration_note") or ""
        if not (insights or findings):
            return
        if insights:
            state.payload["hippograph_insights"] = insights
        if findings:
            state.payload["market_findings"] = findings
        if evidence:
            state.payload["market_evidence"] = evidence       # structured (frontend/agents)
        if note:
            state.payload["market_evidence_note"] = note      # narration-ready preamble (S2)
        if isinstance(state.kv, dict):  # flow into THIS turn's NQE agent (state.kv) + persist next turn
            state.kv["hippograph_insights"] = insights
            if findings:
                state.kv["market_findings"] = findings
        persisted = mem.get_kv(state.uid) or {}
        persisted["hippograph_insights"] = insights
        mem.set_kv(state.uid, persisted)
        log_trace_event(trace_id=state.trace_id, event_type="market_intelligence", source_type="agent",
                        source_id="Market_Intelligence_Agent", target_type="recommendation",
                        target_id=state.decision_id,
                        payload={"insights": len(insights), "findings": len(findings),
                                 "needs_market_evidence": bool(mi.get("needs_market_evidence"))})
    except Exception as exc:
        record_partial_failure("market_intelligence", exc, trace_id=state.trace_id)


def _nudge(state: IntelligenceStageState, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not (state.flags.get("RANKING_NUDGE_EXPERIMENT_ENABLED", False) and not state.simulate and results):
        return results
    try:
        from src.app.models.db import db_session
        from src.app.services.experiment_ops import adaptation_killed, canary_assignment
        from src.app.services.experiments import is_experiment_live, record_assignment
        from src.app.services.ranking_nudge import apply_experiment_nudge
        if adaptation_killed():
            return results  # global kill switch — no adaptation, regardless of experiment status
        exp_id = str(state.flags.get("RANKING_NUDGE_EXPERIMENT_ID") or "ranking_nudge_v1")
        subject = str(state.uid_hash or state.uid or "")
        try:
            canary = float(state.flags.get("RANKING_NUDGE_CANARY_FRACTION") or 0.1)
        except Exception:
            canary = 0.1
        try:
            max_items = int(state.flags.get("RANKING_NUDGE_MAX_ITEMS") or 3)
        except Exception:
            max_items = 3
        # SMALL CANARY: only a fraction of subjects are eligible for treatment (the rest are control)
        variant = canary_assignment(experiment_id=exp_id, subject=subject, canary_fraction=canary)
        recall_ids = [i.get("id") for i in (state.payload.get("hippograph_insights") or [])
                      if isinstance(i, dict) and i.get("kind") == "product"]
        with db_session() as db:
            live = is_experiment_live(db, exp_id)
            record_assignment(db, experiment_id=exp_id, subject_hash=subject, variant=variant)
            db.commit()
        nudged = apply_experiment_nudge(results, recall_ids=recall_ids, assignment=variant, live=live,
                                        max_nudged_items=max_items)
        if nudged is not results:
            results = nudged
            state.payload["results"] = results
        state.payload["ranking_experiment"] = {
            "experiment_id": exp_id, "variant": variant, "live": bool(live),
            "nudged": sum(1 for r in results if isinstance(r, dict) and r.get("_nudge_delta")),
        }
        log_trace_event(trace_id=state.trace_id, event_type="ranking_nudge", source_type="agent",
                        source_id="ExperimentGate", target_type="recommendation", target_id=state.decision_id,
                        payload=state.payload["ranking_experiment"])
    except Exception as exc:
        record_partial_failure("ranking_nudge", exc, trace_id=state.trace_id)
    return results


def run_intelligence_stage(state: IntelligenceStageState, *, mem) -> List[Dict[str, Any]]:
    """Capture → market-intel → reversible nudge. Returns the (possibly nudged) results list; the
    caller assigns it and (the nudge already set) payload['results']."""
    results = state.results
    _capture(state, results)
    _market_intelligence(state, results, mem=mem)
    return _nudge(state, results)
