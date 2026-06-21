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


# OWASP Agentic AI Top 10 (ASI) tags per consequential action, consistent with the observer's
# vocabulary (security/observer._owasp_agentic_tags). The execution gate IS the OWASP-Agentic
# "excessive agency / tool misuse" control, so EVERY consequential action carries ASI02; higher-risk
# actions add their specific risk. Stamped into the policy_evaluation_log context so every gated
# decision is queryable by framework (OWASP Agentic / PCI Req 10 / ISO 42001 decision logging).
_ACTION_AGENTIC_TAGS = {
    "bank_change": ["ASI09:HumanAgentTrustExploitation", "ASI03:IdentityPrivilegeAbuse"],
    "supplier_pay": ["ASI09:HumanAgentTrustExploitation"],
    "supplier_add": ["ASI04:AgenticSupplyChainVulnerabilities"],
    "supplier_contact": ["ASI09:HumanAgentTrustExploitation"],
    "purchase_order": ["ASI04:AgenticSupplyChainVulnerabilities"],
    "pii_export": ["ASI03:IdentityPrivilegeAbuse"],
    "account_recovery": ["ASI03:IdentityPrivilegeAbuse", "ASI09:HumanAgentTrustExploitation"],
    "tool_egress": ["ASI07:InsecureInterAgentComms"],
    "fraud_disposition": ["ASI10:RogueAgents"],
}
_DEFAULT_AGENTIC_TAG = "ASI02:ToolMisuse"


def framework_tags(action: str) -> Dict[str, Any]:
    """Compliance framework tags for a consequential action, for the audit context.

    Lets a compliance query pull every gated decision by OWASP Agentic ASI tag, PCI Req 10, or ISO
    42001 decision-logging — turning the policy_evaluation_log into framework-queryable evidence."""
    a = str(action or "").strip().lower()
    agentic = list(dict.fromkeys([_DEFAULT_AGENTIC_TAG] + _ACTION_AGENTIC_TAGS.get(a, [])))
    return {
        "owasp_agentic_top10": agentic,
        "compliance": ["pci_dss_req10_audit_trail", "iso_42001_decision_logging"],
        "control": "execution_gate",
    }


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
    record_policy_decision(action, value_cents, verdict, tenant_id=tenant_id, actor=actor)
    return verdict


def record_policy_decision(
    action: str,
    value_cents: int,
    verdict: PolicyVerdict,
    *,
    tenant_id: Optional[str] = None,
    actor: Optional[str] = None,
    seam: Optional[str] = None,
) -> None:
    """Canonical audit writer — stamp framework tags onto the verdict context and persist it to
    policy_evaluation_log. Shared by decide() and the route_enforcement seam so EVERY consequential
    decision is recorded in the canonical schema, queryable by framework (Req 10 / ISO 42001 / OWASP
    Agentic), independent of the shadow engine. Never raises."""
    try:
        ctx = {**(getattr(verdict, "context", None) or {}), "frameworks": framework_tags(action)}
        if seam:
            ctx["seam"] = seam
        verdict.context = ctx
    except Exception:
        pass
    _log_policy_evaluation(action, value_cents, verdict, tenant_id, actor)
