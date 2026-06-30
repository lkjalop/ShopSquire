"""Governance pulse (agnostic CORE) — the owner/governance VISIBILITY aggregate (deck Step 11).

The owner must be able to OBSERVE the autonomous subsystem WITHOUT becoming a runtime dependency. This reads
the existing audit trails (it writes nothing) and rolls them into four read-only cards:
  • Signal & Decision State — active findings by severity, AI-confidence distribution, current adaptation mode
  • Experiment Health       — live experiment status, rollback count, terminal-decision breakdown, last uplift
  • Policy & Compliance     — policy block rate + reasons, contact-suppression rate by region, exception count
  • Operational Pressure    — finding counts by type, critical count, total signals

Vertical-blind: action_type / finding_type / channel / region are OPAQUE labels — it COUNTS and RATES them,
nothing more (no product vocabulary, no hardcoded category names). Pure read; never raises — every source is
best-effort and falls back to zero so a missing table can't sink the dashboard.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("shopsquire.governance_pulse")

DEFAULT_TENANT = "default"
# The ranking experiment + its outcomes are GLOBAL (not per-tenant); the experiment card always reads here.
EXPERIMENT_TENANT = "default"


def _kill_switch_on() -> bool:
    return str(os.getenv("ADAPTATION_KILL_SWITCH", "0")).strip().lower() in ("1", "true", "yes", "on")


def _hippograph_mode() -> str:
    raw = str(os.getenv("HIPPOGRAPH_FEEDBACK_ENABLED", "") or "").strip().lower()
    if raw == "shadow":
        return "shadow"
    if raw in ("1", "true", "yes", "on", "live"):
        return "live"
    return "off"


def _confidence_bucket(c: float) -> str:
    """Low (<0.5) / Medium (<0.8) / High — the deck's 'AI confidence distribution'."""
    try:
        v = float(c)
    except (TypeError, ValueError):
        return "low"
    if v < 0.5:
        return "low"
    if v < 0.8:
        return "medium"
    return "high"


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _count_by(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows or []:
        k = str((r or {}).get(key) or "unknown")
        out[k] = out.get(k, 0) + 1
    return out


def governance_pulse(db, *, tenant_id: str = DEFAULT_TENANT, window_limit: int = 500) -> Dict[str, Any]:
    """The four-card governance snapshot. Each source is read best-effort; any failure degrades that card to
    zeros rather than failing the whole pulse."""
    tid = str(tenant_id or DEFAULT_TENANT)

    # ── sources (every one best-effort) ──────────────────────────────────────
    findings: List[Any] = []
    try:
        from src.app.services.market_analysis import load_recent_findings
        findings = load_recent_findings(db, limit=window_limit, tenant_id=tid) or []
    except Exception as exc:
        logger.debug("pulse: findings unavailable: %s", exc)

    gate_audit: List[Dict[str, Any]] = []
    try:
        from src.app.services.adaptive_action_gate import load_recent_audit as load_gate_audit
        gate_audit = load_gate_audit(db, limit=window_limit, tenant_id=tid) or []
    except Exception as exc:
        logger.debug("pulse: gate audit unavailable: %s", exc)

    contact_audit: List[Dict[str, Any]] = []
    try:
        from src.app.services.contact_governance import load_recent_audit as load_contact_audit
        contact_audit = load_contact_audit(db, limit=window_limit, tenant_id=tid) or []
    except Exception as exc:
        logger.debug("pulse: contact audit unavailable: %s", exc)

    # The ranking experiment is GLOBAL (experiment_run has no tenant) and its outcomes are recorded under the
    # default tenant — so the experiment card is ALWAYS sourced from there, regardless of the pulse's display
    # tenant. Mixing a global status with tenant-scoped outcome counts produced a 'reverted but 0 rollbacks'
    # split-brain in the replay-demo view.
    outcomes: List[Dict[str, Any]] = []
    try:
        from src.app.services.market_outcome import load_recent_outcomes
        outcomes = load_recent_outcomes(db, limit=window_limit, tenant_id=EXPERIMENT_TENANT) or []
    except Exception as exc:
        logger.debug("pulse: outcomes unavailable: %s", exc)

    experiment: Dict[str, Any] = {}
    try:
        from src.app.services.experiment_console import state as experiment_state
        experiment = experiment_state(db) or {}
    except Exception as exc:
        logger.debug("pulse: experiment state unavailable: %s", exc)

    # ── Card 1 · Signal & Decision State ─────────────────────────────────────
    sev_counts: Dict[str, int] = {"info": 0, "warn": 0, "critical": 0}
    for f in findings:
        s = str(getattr(f, "severity", "") or (f.get("severity") if isinstance(f, dict) else "") or "info").lower()
        sev_counts[s] = sev_counts.get(s, 0) + 1
    conf_dist: Dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    for r in gate_audit:
        conf_dist[_confidence_bucket(r.get("confidence", 0.0))] += 1
    signal_decision = {
        "active_findings": len(findings),
        "findings_by_severity": sev_counts,
        "ai_confidence_distribution": conf_dist,
        "adaptation_mode": {
            "kill_switch": _kill_switch_on(),
            "hippograph_mode": _hippograph_mode(),
            "experiment_live": bool(experiment.get("live")),
        },
    }

    # ── Card 2 · Experiment Health ───────────────────────────────────────────
    decision_breakdown = _count_by(outcomes, "decision")
    rollback_count = sum(1 for o in outcomes if o.get("reverted") or str(o.get("decision")) == "revert")
    last_uplift = experiment.get("last_uplift")
    if last_uplift is None and outcomes:
        last_uplift = outcomes[0].get("uplift_pct")
    experiment_health = {
        "experiment_id": experiment.get("experiment_id"),
        "scope": "global",  # the ranking experiment is global; outcomes read from EXPERIMENT_TENANT
        "status": experiment.get("status", "absent"),
        "live": bool(experiment.get("live")),
        "assignments": experiment.get("assignments", {}),
        "outcomes_recorded": len(outcomes),
        "decision_breakdown": decision_breakdown,
        "rollback_count": rollback_count,
        "last_decision": experiment.get("last_decision") or (outcomes[0].get("decision") if outcomes else None),
        "last_uplift_pct": last_uplift,
    }

    # ── Card 3 · Policy & Compliance ─────────────────────────────────────────
    gate_total = len(gate_audit)
    gate_blocks = [r for r in gate_audit if str(r.get("decision")) == "deny"]
    block_reasons = _count_by(gate_blocks, "reason")
    contact_total = len(contact_audit)
    contact_suppressed = [r for r in contact_audit if str(r.get("decision")) != "allow"]
    suppression_by_region = _count_by(contact_suppressed, "region")
    policy_compliance = {
        "actions_evaluated": gate_total,
        "actions_blocked": len(gate_blocks),
        "policy_block_rate": _rate(len(gate_blocks), gate_total),
        "block_reasons": block_reasons,
        "contacts_evaluated": contact_total,
        "contacts_suppressed": len(contact_suppressed),
        "contact_suppression_rate": _rate(len(contact_suppressed), contact_total),
        "suppression_by_region": suppression_by_region,
        "exception_count": len(gate_blocks) + len(contact_suppressed),
    }

    # ── Card 4 · Operational Pressure ────────────────────────────────────────
    findings_by_type: Dict[str, int] = {}
    for f in findings:
        t = str(getattr(f, "finding_type", "") or (f.get("finding_type") if isinstance(f, dict) else "") or "unknown")
        findings_by_type[t] = findings_by_type.get(t, 0) + 1
    operational_pressure = {
        "findings_by_type": findings_by_type,
        "critical_findings": sev_counts.get("critical", 0),
        "total_signal_findings": len(findings),
        "open_action_proposals": _count_proposals(db, tid),
    }

    return {
        "tenant_id": tid,
        "window_limit": window_limit,
        "signal_decision_state": signal_decision,
        "experiment_health": experiment_health,
        "policy_compliance": policy_compliance,
        "operational_pressure": operational_pressure,
    }


def _count_proposals(db, tenant_id: str) -> int:
    try:
        from src.app.services.shadow_actions import load_recent_proposals
        return len(load_recent_proposals(db, limit=500, tenant_id=tenant_id) or [])
    except Exception:
        return 0
