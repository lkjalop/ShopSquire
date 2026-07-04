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

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.app.services.decision_log import log_trace_event
from src.app.services.safe_stage import record_partial_failure


def _market_min_confidence() -> float:
    """Calibrated confidence floor for the Phase-3 storefront-adaptation levers (ranking + sales-response
    nudge). The shared adaptive_action_gate defaults its global floor to 0.0 ("off until calibrated"), which
    is right for procurement's use of the gate but would let a storefront nudge act on a NOISE signal the
    moment the flag is flipped. So the market levers pass an explicit floor — MARKET_ADAPTIVE_MIN_CONFIDENCE,
    default 0.6 — so a weak demand signal is DENIED (governed) while a strong one adapts. Never raises."""
    try:
        return float(os.getenv("MARKET_ADAPTIVE_MIN_CONFIDENCE", "0.6") or 0.6)
    except (TypeError, ValueError):
        return 0.6


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


def _adaptation_exposure(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The adaptation(s) this turn was exposed to, in decision_ref terms (the M6 close-loop key).
    Recorded into the E0 decision's context so a LATER conversion can attribute its value back to the
    adaptation that shaped the ranking — treatment AND control exposures both matter (uplift needs
    both sides). Empty dict when no adaptation touched the turn."""
    out: Dict[str, Any] = {}
    re_ = payload.get("ranking_experiment")
    if isinstance(re_, dict) and re_.get("experiment_id"):
        out[str(re_["experiment_id"])] = str(re_.get("variant") or "control")
    sr = payload.get("sales_response_nudge")
    if isinstance(sr, dict) and int(sr.get("applied") or 0) > 0:
        out["sales_response"] = str(sr.get("demand_trend") or "applied")
    return out


def _capture(state: IntelligenceStageState, results: List[Dict[str, Any]]) -> None:
    if not (state.flags.get("ATTRIBUTION_ENABLED", True) and not state.simulate):
        return
    try:
        from src.app.models.db import db_session
        from src.app.services.attribution import record_decision
        from src.app.services.bandit_context import get_bandit_arm
        skus = [r.get("sku") for r in results if isinstance(r, dict) and r.get("sku")]
        context: Dict[str, Any] = {"budget_max": state.constraints.get("budget_max"),
                                   "use_case": state.constraints.get("use_case")}
        exposure = _adaptation_exposure(state.payload)
        if exposure:
            context["adaptations"] = exposure  # ref → segment, consumed by attribute_order (M6)
        # arm = the LinUCB ranking arm (for the E3 reward), variant = the A/B arm — distinct.
        with db_session() as db:
            record_decision(db, trace_id=state.trace_id, decision_id=state.decision_id, uid_hash=state.uid_hash,
                            skus=skus, surface="recommend", arm=get_bandit_arm(),
                            variant=(state.proposal or {}).get("ab_variant"),
                            context=context)
            db.commit()
    except Exception as exc:
        record_partial_failure("attribution_capture", exc, trace_id=state.trace_id)


def _mi_mode(flags: Dict[str, Any]) -> str:
    """HIPPOGRAPH_FEEDBACK_ENABLED as a MODE, not just a boolean:
      • 'live'   — inject the market signals into the response + session (decision-affecting);
      • 'shadow' — COMPUTE + LOG the signals (observability) but DO NOT mutate the buyer-facing decision —
                   the governed first rung: watch demand/competitor signals before trusting them;
      • 'off'    — skip entirely (default).
    'shadow' is the safe rollout: signals appear in the decision trace, never in the buyer's response."""
    raw = str(flags.get("HIPPOGRAPH_FEEDBACK_ENABLED", "") or "").strip().lower()
    if raw == "shadow":
        return "shadow"
    if raw in ("1", "true", "yes", "on", "live"):
        return "live"
    return "off"


def _market_intelligence(state: IntelligenceStageState, results: List[Dict[str, Any]], *, mem) -> None:
    mode = _mi_mode(state.flags)
    if mode == "off" or state.simulate:
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
        # LIVE mutates the response + memory (decision-affecting). SHADOW does NOT — it only observes via the
        # trace below, so demand/competitor signals can be watched (and trusted) before they steer a decision.
        if mode == "live":
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
        # BOTH modes emit the observability trace — shadow logs the signals WITHOUT acting on them.
        log_trace_event(trace_id=state.trace_id, event_type="market_intelligence", source_type="agent",
                        source_id="Market_Intelligence_Agent", target_type="recommendation",
                        target_id=state.decision_id,
                        payload={"mode": mode, "applied": mode == "live",
                                 "insights": len(insights), "findings": len(findings),
                                 "needs_market_evidence": bool(mi.get("needs_market_evidence")),
                                 "signal_labels": [str(i.get("label")) for i in insights[:5]
                                                   if isinstance(i, dict) and i.get("label")]})
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
        # UNIFIED GATE: an actual ranking adjustment (treatment + live + something to boost) must be
        # AUTHORIZED — confidence threshold + action authorization + a DURABLE audit record. A DENY
        # skips the nudge. The confidence is the strength of the hippograph recall driving it.
        gate_reason = None
        if variant == "treatment" and live and recall_ids:
            from src.app.services.adaptive_action_gate import authorize
            _conf = max((float(i.get("score") or 0.0) for i in (state.payload.get("hippograph_insights") or [])
                        if isinstance(i, dict) and i.get("kind") == "product"), default=1.0)
            with db_session() as gdb:
                gate = authorize(gdb, action_type="adjust_ranking", confidence=_conf,
                                 min_confidence=_market_min_confidence(),
                                 subject=subject, target=str(recall_ids[0]))
            gate_reason = gate.reason
            if not gate.allowed:
                state.payload["ranking_experiment"] = {"experiment_id": exp_id, "variant": variant,
                    "live": bool(live), "nudged": 0, "gate": gate_reason}
                return results  # authorized DENY — no adjustment
        nudged = apply_experiment_nudge(results, recall_ids=recall_ids, assignment=variant, live=live,
                                        max_nudged_items=max_items)
        if nudged is not results:
            results = nudged
            state.payload["results"] = results
        state.payload["ranking_experiment"] = {
            "experiment_id": exp_id, "variant": variant, "live": bool(live),
            "nudged": sum(1 for r in results if isinstance(r, dict) and r.get("_nudge_delta")),
            "gate": gate_reason,
        }
        log_trace_event(trace_id=state.trace_id, event_type="ranking_nudge", source_type="agent",
                        source_id="ExperimentGate", target_type="recommendation", target_id=state.decision_id,
                        payload=state.payload["ranking_experiment"])
    except Exception as exc:
        record_partial_failure("ranking_nudge", exc, trace_id=state.trace_id)
    return results


def _inventory_position(row: Dict[str, Any], *, overstock_units: int) -> str:
    """Commerce-generic inventory position for one candidate (vertical-blind: stock COUNTS only, no product
    vocab): near-empty → shortage (recede if we can't ship), heavy overstock → surplus (surface to clear),
    else balanced. Falls back to the in_stock boolean (OOS-only) when no count is present."""
    s = row.get("stock")
    if isinstance(s, (int, float)):
        s = int(s)
        if s <= 2:
            return "shortage"
        if s >= overstock_units:
            return "surplus"
        return "balanced"
    ins = row.get("in_stock")
    if ins is False or ins == 0:
        return "shortage"
    return "balanced"


def _sales_response_nudge(state: IntelligenceStageState, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """M5 consume #2 — Phase-3 LOW-RISK adaptation: a demand-aware ranking nudge. Given the shared demand
    trend + each item's inventory position, surplus/hot items get a small BOUNDED boost and can't-ship
    shortages recede. Flag-gated default-OFF (SALES_RESPONSE_NUDGE_ENABLED), respects the global kill switch,
    AUTHORIZED through the adaptive action gate (Policy authorizes), bounded + reversible + audited. Returns
    ``results`` unchanged when off / denied / nothing actionable."""
    if not (state.flags.get("SALES_RESPONSE_NUDGE_ENABLED", False) and not state.simulate and results):
        return results
    try:
        from src.app.models.db import db_session
        from src.app.services.experiment_ops import adaptation_killed
        from src.app.services.market_analysis import load_recent_findings
        from src.app.services.ranking_nudge import apply_sales_response_nudge
        from src.app.services.sales_response_policy import classify_demand_trend, promotion_biases
        if adaptation_killed():
            return results  # global kill switch — no adaptation
        try:
            max_items = int(state.flags.get("SALES_RESPONSE_NUDGE_MAX_ITEMS") or 6)
        except (TypeError, ValueError):
            max_items = 6
        try:
            overstock = int(state.flags.get("SALES_RESPONSE_OVERSTOCK_UNITS") or 20)
        except (TypeError, ValueError):
            overstock = 20
        with db_session() as db:
            findings = load_recent_findings(db, limit=50)
        demand_trend, conf = classify_demand_trend(findings)
        inv_by_sku = {str(r.get("sku")): _inventory_position(r, overstock_units=overstock)
                      for r in results if isinstance(r, dict) and r.get("sku")}
        actionable = {s: b for s, b in promotion_biases(demand_trend, inv_by_sku).items()
                      if b in ("boost", "suppress")}
        if not actionable:
            return results  # only a 'steady' picture → nothing to adjust
        # UNIFIED GATE — the adaptation is AUTHORIZED (confidence = demand-signal strength) + durable audit.
        from src.app.services.adaptive_action_gate import authorize
        with db_session() as gdb:
            gate = authorize(gdb, action_type="adjust_ranking", confidence=float(conf),
                             min_confidence=_market_min_confidence(),
                             subject=str(state.uid_hash or state.uid or ""), target=str(next(iter(actionable))))
        if not gate.allowed:
            state.payload["sales_response_nudge"] = {"applied": 0, "gate": gate.reason,
                                                     "demand_trend": demand_trend}
            return results  # authorized DENY — no adjustment
        nudged = apply_sales_response_nudge(results, bias_by_sku=actionable, max_nudged_items=max_items)
        if nudged is not results:
            results = nudged
            state.payload["results"] = results
        state.payload["sales_response_nudge"] = {
            "applied": sum(1 for r in results if isinstance(r, dict) and r.get("_sales_response_delta")),
            "demand_trend": demand_trend,
            "boosted": sum(1 for b in actionable.values() if b == "boost"),
            "suppressed": sum(1 for b in actionable.values() if b == "suppress"),
            "gate": gate.reason,
        }
        log_trace_event(trace_id=state.trace_id, event_type="sales_response_applied", source_type="agent",
                        source_id="Sales_Response_Agent", target_type="recommendation", target_id=state.decision_id,
                        payload=state.payload["sales_response_nudge"])
    except Exception as exc:
        record_partial_failure("sales_response_nudge", exc, trace_id=state.trace_id)
    return results


def run_intelligence_stage(state: IntelligenceStageState, *, mem) -> List[Dict[str, Any]]:
    """Market-intel → reversible nudge(s) → capture. Returns the (possibly nudged) results list; the
    caller assigns it and (the nudge already set) payload['results']. Capture runs LAST deliberately:
    the E0 decision must record what was ACTUALLY SHOWN (post-nudge order) plus which adaptation(s)
    the turn was exposed to — the exposure a later conversion attributes back to (M6 close-loop)."""
    results = state.results
    _market_intelligence(state, results, mem=mem)
    results = _nudge(state, results)                    # experiment (hippograph recall) nudge
    results = _sales_response_nudge(state, results)     # M5 demand-aware nudge (Phase-3)
    _capture(state, results)
    return results
