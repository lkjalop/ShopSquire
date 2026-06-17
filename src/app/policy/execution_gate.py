"""Execution gate — the single decision point for consequential actions (P3).

The moat centerpiece: David's 5-step rule ("AI infers; policy decides; execution acts;
audit records") and CaMeL's control/data separation both reduce to ONE invariant —

    every consequential action passes through ONE gate that DECIDES and LOGS.

Today that decision is scattered across three mechanisms (authorization_engine,
action_authority_matrix, route_enforcement) and ~9 router call-sites. This module is
the canonical entry point that unifies them behind `decide()`. It does two things the
scattered callers don't reliably do together:

  1. evaluates the action against the deterministic authority matrix (fail-closed), and
  2. ALWAYS writes a policy_evaluation_log row — so there is no consequential action
     without a logged, replayable verdict (the audit/data-gravity guarantee).

Strangler: this is the new canonical path; existing callers migrate to it over time.
`decide()` RETURNS a verdict (never raises) so the caller chooses how to enforce
(allow -> execute; else -> block / escalate / bounded-autonomous-outcome). Never raises.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

from src.app.policy.action_authority_matrix import AuthDecision, PolicyVerdict, evaluate as _evaluate

_log = logging.getLogger(__name__)

# Consequential actions that MUST pass the gate (mirrors David's "never bypass" list).
CONSEQUENTIAL_ACTIONS = frozenset({
    "refund", "reshipment", "order_modification", "order_accept", "cancellation",
    "bank_change", "supplier_pay", "supplier_add", "supplier_contact", "purchase_order",
    "discount", "bundle_commit", "inventory_reservation", "pii_export", "account_recovery",
    "fraud_disposition", "tool_egress",
})


def is_consequential(action: str) -> bool:
    return str(action or "").strip().lower() in CONSEQUENTIAL_ACTIONS


def _log_policy_evaluation(
    action: str, value_cents: int, verdict: PolicyVerdict,
    tenant_id: Optional[str], actor: Optional[str],
) -> None:
    """Persist the verdict to policy_evaluation_log (P2 table). Defensive — a logging
    failure must never block the decision, but it IS the audit guarantee, so warn."""
    try:
        from sqlalchemy import text as _t
        from src.app.models.db import db_session
        with db_session() as db:
            db.execute(
                _t(
                    "INSERT INTO policy_evaluation_log "
                    "(id, decision_id, tenant_id, action, value_cents, decision, rule_id, "
                    " reason, authority, context) VALUES "
                    "(:id, :did, :tenant, :action, :val, :decision, :rule, :reason, :auth, :ctx)"
                ),
                {
                    "id": uuid.uuid4().hex,
                    "did": str((verdict.context or {}).get("decision_id") or ""),
                    "tenant": tenant_id,
                    "action": str(action),
                    "val": int(value_cents or 0),
                    "decision": str(verdict.decision.value),
                    "rule": str(verdict.rule_id or ""),
                    "reason": str(verdict.reason or ""),
                    "auth": "matrix",
                    "ctx": json.dumps({"actor": actor, **(verdict.context or {})}, default=str)[:4000],
                },
            )
            db.commit()
    except Exception as exc:
        _log.warning("policy_evaluation_log write failed for action=%s: %s", action, exc)


def decide(
    action: str,
    *,
    value_cents: int = 0,
    context: Optional[Dict[str, Any]] = None,
    actor: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> PolicyVerdict:
    """Evaluate a consequential action and log the verdict. Returns a PolicyVerdict;
    the caller enforces. Fail-closed: an unmapped action returns HUMAN_REVIEW (via the
    matrix default), never ALLOW. Never raises."""
    try:
        verdict = _evaluate(action, value_aud_cents=int(value_cents or 0), context=context or {})
    except Exception as exc:
        _log.warning("execution_gate.decide evaluate failed for %s: %s — failing closed", action, exc)
        verdict = PolicyVerdict(
            decision=AuthDecision.HUMAN_REVIEW,
            reason="gate evaluation error — fail closed",
            rule_id="GATE_ERROR",
            alert_siem=True,
            context=context or {},
        )
    _log_policy_evaluation(action, value_cents, verdict, tenant_id, actor)
    return verdict
