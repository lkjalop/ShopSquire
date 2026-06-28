"""Adaptive-action authorization gate (agnostic CORE) — the deck's "Policy authorizes. Audit records."

ONE chokepoint every customer-impacting adaptive action passes BEFORE it executes (ranking nudge,
template phrasing, low-stock suppression, offers, campaigns). It unifies what was scattered:

  1. global kill switch     — ADAPTATION_KILL_SWITCH forces DENY everywhere (shared with experiment_ops).
  2. action authorization   — the action_type must be in the allowed set (deny an unknown/unbounded one).
  3. confidence threshold    — the deck's "minimum signal confidence before an action is authorized"
                              (ADAPTIVE_MIN_CONFIDENCE, default 0.0 = off until calibrated).
  4. durable audit           — EVERY decision (allow + deny) is recorded; if an ALLOW cannot be
                              persisted, it FAILS CLOSED to deny(audit_unavailable) — no unaudited action.

Returns ALLOW or DENY(reason); never raises into the caller (a gate error fails closed). Vertical-blind.

Table: adaptive_action_audit(id, tenant_id, action_type, decision, reason, confidence, subject, target,
                            created_at)
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

ALLOW = "allow"
DENY_KILLED = "killed"
DENY_NOT_AUTHORIZED = "action_not_authorized"
DENY_LOW_CONFIDENCE = "low_confidence"
DENY_AUDIT_UNAVAILABLE = "audit_unavailable"
DENY_ERROR = "error_fail_closed"

# the bounded set of action types the autonomous layer may take — an unknown type is denied (the deck's
# "never an unbounded or undefined response").
ALLOWED_ACTION_TYPES = frozenset({
    "adjust_ranking", "suppress_low_stock", "revise_support_copy", "template_phrasing", "offer", "campaign",
    # procurement: the confidence-gated "engage an external party" + "generate options" steps. Drafting
    # is authorized here (and still requires a human to SEND); low confidence routes to NQE/human.
    "supplier_contact_draft", "fulfillment_options",
    # WS-C: flag-gated AUTONOMOUS RFQ send (an RFQ is non-binding — no price/PO). Authorized here only
    # after autonomous_send's guards pass; the action-gate adds kill-switch + confidence + durable audit.
    "supplier_rfq_send",
})

_DDL = """
CREATE TABLE IF NOT EXISTS adaptive_action_audit (
    id TEXT PRIMARY KEY,
    tenant_id TEXT DEFAULT 'default',
    action_type TEXT,
    decision TEXT,
    reason TEXT,
    confidence REAL,
    subject TEXT,
    target TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_adaptive_audit_action ON adaptive_action_audit(tenant_id, action_type, created_at)",
)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    action_type: str
    confidence: float
    detail: Dict[str, Any] = field(default_factory=dict)


def ensure_table(db) -> None:
    db.execute(text(_DDL))
    for stmt in _INDEXES:
        db.execute(text(stmt))


def _kill_switch() -> bool:
    # shares the global brake with experiment_ops.adaptation_killed (kept import-light + duplication-free)
    try:
        from src.app.services.experiment_ops import adaptation_killed
        return adaptation_killed()
    except Exception:
        return str(os.getenv("ADAPTATION_KILL_SWITCH", "0")).strip().lower() in ("1", "true", "yes", "on")


def _min_confidence(explicit: Optional[float]) -> float:
    if explicit is not None:
        return float(explicit)
    try:
        return float(os.getenv("ADAPTIVE_MIN_CONFIDENCE", "0") or 0.0)
    except Exception:
        return 0.0


def _write_audit(db, d: GateDecision, *, subject: Optional[str], target: Optional[str], tenant_id: str) -> bool:
    try:
        db.execute(text("INSERT INTO adaptive_action_audit (id, tenant_id, action_type, decision, reason, "
                        "confidence, subject, target) VALUES (:i,:t,:at,:d,:r,:c,:s,:tg)"),
                   {"i": str(uuid.uuid4()), "t": tenant_id, "at": d.action_type,
                    "d": "allow" if d.allowed else "deny", "r": d.reason, "c": float(d.confidence),
                    "s": subject, "tg": target})
        return True
    except Exception:
        return False


def authorize(
    db,
    *,
    action_type: str,
    confidence: float = 1.0,
    subject: Optional[str] = None,
    target: Optional[str] = None,
    min_confidence: Optional[float] = None,
    allowed_types: Optional[frozenset] = None,
    tenant_id: str = DEFAULT_TENANT,
    write_audit: bool = True,
) -> GateDecision:
    """Authorize one adaptive action. Returns ALLOW or DENY(reason) and (by default) writes a durable
    audit row. Fails CLOSED on any error or unpersistable allow. Never raises."""
    at = str(action_type or "").strip()
    tid = str(tenant_id).strip() or DEFAULT_TENANT
    try:
        conf = float(confidence)
    except Exception:
        conf = 0.0
    allow_set = allowed_types or ALLOWED_ACTION_TYPES
    try:
        if _kill_switch():
            decision = GateDecision(False, DENY_KILLED, at, conf)
        elif at not in allow_set:
            decision = GateDecision(False, DENY_NOT_AUTHORIZED, at, conf)
        elif conf < _min_confidence(min_confidence):
            decision = GateDecision(False, DENY_LOW_CONFIDENCE, at, conf,
                                    detail={"min_confidence": _min_confidence(min_confidence)})
        else:
            decision = GateDecision(True, ALLOW, at, conf)
    except Exception:
        decision = GateDecision(False, DENY_ERROR, at, conf)

    if write_audit and db is not None:
        ensure_table(db)
        ok = _write_audit(db, decision, subject=subject, target=target, tenant_id=tid)
        if decision.allowed and not ok:
            decision = GateDecision(False, DENY_AUDIT_UNAVAILABLE, at, conf)  # no unaudited action
            _write_audit(db, decision, subject=subject, target=target, tenant_id=tid)
        try:
            db.commit()
        except Exception:
            return decision
    return decision


def record_decision(db, *, action_type: str, decision: str, reason: str = "", confidence: float = 0.0,
                    subject: Optional[str] = None, target: Optional[str] = None,
                    tenant_id: str = DEFAULT_TENANT) -> bool:
    """Write ONE audit row for a decision made OUTSIDE authorize() — e.g. an autonomous escalation that
    never reached the gate (decision='escalate'). Best-effort; returns whether it persisted. This is the
    only sanctioned way to record a non allow/deny decision so the audit view shows escalations + reasons."""
    if db is None:
        return False
    try:
        ensure_table(db)
        db.execute(text("INSERT INTO adaptive_action_audit (id, tenant_id, action_type, decision, reason, "
                        "confidence, subject, target) VALUES (:i,:t,:at,:d,:r,:c,:s,:tg)"),
                   {"i": str(uuid.uuid4()), "t": str(tenant_id).strip() or DEFAULT_TENANT,
                    "at": str(action_type or ""), "d": str(decision), "r": str(reason or ""),
                    "c": float(confidence or 0.0), "s": subject, "tg": target})
        db.commit()
        return True
    except Exception:
        return False


def load_recent_audit(db, *, limit: int = 100, tenant_id: str = DEFAULT_TENANT,
                      action_type: Optional[str] = None) -> List[Dict[str, Any]]:
    if db is None:
        return []
    try:
        ensure_table(db)
        sql = ("SELECT action_type, decision, reason, confidence, subject, target, created_at "
               "FROM adaptive_action_audit WHERE COALESCE(tenant_id,'default')=:t")
        params: Dict[str, Any] = {"lim": int(limit), "t": str(tenant_id).strip() or DEFAULT_TENANT}
        if action_type:
            sql += " AND action_type=:at"
            params["at"] = str(action_type)
        sql += " ORDER BY created_at DESC LIMIT :lim"
        rows = db.execute(text(sql), params).fetchall()
    except Exception:
        return []
    return [{"action_type": r[0], "decision": r[1], "reason": r[2], "confidence": float(r[3] or 0.0),
             "subject": r[4], "target": r[5], "created_at": r[6]} for r in rows]
