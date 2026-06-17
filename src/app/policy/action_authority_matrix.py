"""CRIT-05 — Deterministic policy decision engine.

The LLM RECOMMENDS.  This module AUTHORISES or BLOCKS.

Never allow the model to be the final arbiter on high-impact actions
(refunds, bank-detail changes, supplier onboarding, PII export, account
recovery).  Every call to ``evaluate()`` produces a ``PolicyVerdict`` that
the caller MUST check before executing the underlying action.

Framework alignment
-------------------
* EU AI Act Art 9 + 14  — risk management + human oversight
* ISO 42001 Cl 6.1.2     — AI risk classification and treatment
* NIST AI RMF GOVERN-1.2 — formal action-authority assignment
* PCI DSS Req 12.3       — targeted risk analysis for high-value operations
* GDPR Art 22            — human-in-the-loop for automated decisions that
                           materially affect persons
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision types
# ---------------------------------------------------------------------------

class AuthDecision(str, Enum):
    ALLOW        = "allow"           # Execute immediately
    DUAL_CONTROL = "dual_control"    # Needs a second authorised approver
    HUMAN_REVIEW = "human_review"    # Queue for human, freeze the action
    BLOCK        = "block"           # Hard block — create ticket + alert SIEM


@dataclass
class PolicyVerdict:
    decision:       AuthDecision
    reason:         str
    rule_id:        str              = ""
    requires_2fa:   bool             = False
    alert_siem:     bool             = False
    create_ticket:  bool             = False
    ticket_priority: str             = "high"
    context:        Dict[str, Any]   = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == AuthDecision.ALLOW

    @property
    def blocked(self) -> bool:
        return self.decision == AuthDecision.BLOCK


# ---------------------------------------------------------------------------
# Authority matrix rules
# ---------------------------------------------------------------------------
# Each rule is matched in order; first match wins.
# ``max_aud_cents`` = None means "any value" (catch-all for that action).
# Thresholds are in AUD cents to avoid float-comparison issues.
# ---------------------------------------------------------------------------

_RULES: List[Dict[str, Any]] = [
    # -----------------------------------------------------------------------
    # Refunds
    # -----------------------------------------------------------------------
    {
        "id": "REF-01",
        "action": "refund",
        "max_aud_cents": 5_000,          # ≤ $50 AUD
        "decision": AuthDecision.ALLOW,
        "reason": "Small refund — within autonomous approval threshold",
    },
    {
        "id": "REF-02",
        "action": "refund",
        "max_aud_cents": 50_000,         # $50–$500 AUD
        "decision": AuthDecision.DUAL_CONTROL,
        "reason": "Mid-value refund requires a second approver",
        "requires_2fa": True,
    },
    {
        "id": "REF-03",
        "action": "refund",
        "max_aud_cents": None,           # > $500 AUD
        "decision": AuthDecision.HUMAN_REVIEW,
        "reason": "High-value refund frozen — queued for human review",
        "alert_siem": True,
        "create_ticket": True,
        "ticket_priority": "critical",
    },
    # -----------------------------------------------------------------------
    # Bank / payment-destination changes  (always blocked — OOB verification)
    # -----------------------------------------------------------------------
    {
        "id": "BANK-01",
        "action": "bank_change",
        "max_aud_cents": None,
        "decision": AuthDecision.BLOCK,
        "reason": "Bank-detail changes require out-of-band verification — AI cannot authorise",
        "alert_siem": True,
        "create_ticket": True,
        "ticket_priority": "critical",
    },
    # -----------------------------------------------------------------------
    # Supplier management
    # -----------------------------------------------------------------------
    {
        "id": "SUP-01",
        "action": "supplier_add",
        "max_aud_cents": None,
        "decision": AuthDecision.HUMAN_REVIEW,
        "reason": "New supplier requires compliance vetting before onboarding",
        "create_ticket": True,
        "ticket_priority": "high",
    },
    {
        "id": "SUP-02",
        "action": "supplier_pay",
        "max_aud_cents": 100_000,        # ≤ $1000 AUD
        "decision": AuthDecision.DUAL_CONTROL,
        "reason": "Supplier payment requires dual-control authorisation",
        "requires_2fa": True,
    },
    {
        "id": "SUP-03",
        "action": "supplier_pay",
        "max_aud_cents": None,
        "decision": AuthDecision.HUMAN_REVIEW,
        "reason": "Large supplier payment frozen for human review",
        "alert_siem": True,
        "create_ticket": True,
        "ticket_priority": "critical",
    },
    # -----------------------------------------------------------------------
    # PII / data operations
    # -----------------------------------------------------------------------
    {
        "id": "PII-01",
        "action": "pii_export",
        "max_aud_cents": None,
        "decision": AuthDecision.BLOCK,
        "reason": "Bulk PII export blocked — use the approved DSR workflow",
        "alert_siem": True,
        "create_ticket": True,
        "ticket_priority": "critical",
    },
    {
        "id": "PII-02",
        "action": "account_recovery",
        "max_aud_cents": None,
        "decision": AuthDecision.HUMAN_REVIEW,
        "reason": "Account recovery requires identity verification",
        "create_ticket": True,
        "ticket_priority": "high",
    },
    # -----------------------------------------------------------------------
    # Agent egress (tool calls to external URLs)
    # -----------------------------------------------------------------------
    {
        "id": "EGR-01",
        "action": "tool_egress",
        "max_aud_cents": None,
        "decision": AuthDecision.BLOCK,
        "reason": "Agent egress to unlisted domain blocked — add to egress allowlist first",
        "alert_siem": True,
    },
    # -----------------------------------------------------------------------
    # High-value order acceptance
    # -----------------------------------------------------------------------
    {
        "id": "ORD-01",
        "action": "order_accept",
        "max_aud_cents": 500_000,        # ≤ $5000 AUD
        "decision": AuthDecision.ALLOW,
        "reason": "Standard order — within autonomous acceptance threshold",
    },
    {
        "id": "ORD-02",
        "action": "order_accept",
        "max_aud_cents": None,
        "decision": AuthDecision.DUAL_CONTROL,
        "reason": "High-value order requires second approval",
        "requires_2fa": True,
        "create_ticket": True,
        "ticket_priority": "high",
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate(
    action: str,
    value_aud_cents: int = 0,
    context: Optional[Dict[str, Any]] = None,
) -> PolicyVerdict:
    """Evaluate an action against the authority matrix.

    Parameters
    ----------
    action:           One of the ``action`` keys defined in ``_RULES`` above.
    value_aud_cents:  Monetary value of the action in AUD cents (default 0).
    context:          Optional ambient context (user_id, tenant_id, etc.)
                      stored on the verdict for downstream audit logging.

    Returns
    -------
    PolicyVerdict — callers MUST check ``verdict.decision`` (or the convenience
    properties ``verdict.allowed`` / ``verdict.blocked``) before executing.

    Raises
    ------
    Never raises — evaluation failures default to BLOCK so the engine
    always fails closed.
    """
    ctx = dict(context or {})
    ctx.update({"action": action, "value_aud_cents": value_aud_cents})

    try:
        for rule in _RULES:
            if rule["action"] != action:
                continue
            threshold: Optional[int] = rule.get("max_aud_cents")
            if threshold is not None and value_aud_cents > threshold:
                continue                      # Try next rule (higher threshold)
            verdict = PolicyVerdict(
                decision=rule["decision"],
                reason=rule["reason"],
                rule_id=rule.get("id", ""),
                requires_2fa=rule.get("requires_2fa", False),
                alert_siem=rule.get("alert_siem", False),
                create_ticket=rule.get("create_ticket", False),
                ticket_priority=rule.get("ticket_priority", "medium"),
                context=ctx,
            )
            logger.debug(
                "policy_matrix action=%s value_cents=%d rule=%s decision=%s",
                action, value_aud_cents, rule.get("id"), verdict.decision,
            )
            return verdict

        # No matching rule — FAIL CLOSED. An unmapped privileged action is an unknown
        # risk, so it must not execute silently. Freeze + queue for human review (not a
        # hard BLOCK, which would over-alert) and raise it to SIEM for visibility.
        # (Was default-ALLOW — a fail-open hole: any action without an explicit rule
        # executed unchecked. All current callers pass mapped actions, so this only
        # affects genuinely unknown actions.) Override via POLICY_MATRIX_DEFAULT_ALLOW=1
        # ONLY for a deliberate, audited migration window.
        import os as _os
        if str(_os.getenv("POLICY_MATRIX_DEFAULT_ALLOW", "0")).strip().lower() in ("1", "true", "yes"):
            logger.warning("policy_matrix no_rule action=%s value_cents=%d — default ALLOW (override flag set)", action, value_aud_cents)
            return PolicyVerdict(
                decision=AuthDecision.ALLOW,
                reason="No matching policy rule — default allow (POLICY_MATRIX_DEFAULT_ALLOW override)",
                rule_id="DEFAULT_ALLOW_OVERRIDE",
                context=ctx,
            )
        logger.warning("policy_matrix no_rule action=%s value_cents=%d — FAIL CLOSED (human_review)", action, value_aud_cents)
        return PolicyVerdict(
            decision=AuthDecision.HUMAN_REVIEW,
            reason="No matching policy rule — fail closed (unknown action requires human review)",
            rule_id="DEFAULT_FAIL_CLOSED",
            alert_siem=True,
            create_ticket=True,
            ticket_priority="high",
            context=ctx,
        )

    except Exception as exc:
        # Fail closed on any evaluation error
        logger.error("policy_matrix evaluation_error action=%s: %s", action, exc, exc_info=True)
        return PolicyVerdict(
            decision=AuthDecision.BLOCK,
            reason=f"Policy evaluation error — failing closed: {exc}",
            rule_id="ERROR",
            alert_siem=True,
            create_ticket=True,
            ticket_priority="critical",
            context=ctx,
        )


def evaluate_and_raise(
    action: str,
    value_aud_cents: int = 0,
    context: Optional[Dict[str, Any]] = None,
) -> PolicyVerdict:
    """Like ``evaluate()`` but raises ``PolicyBlockedError`` on BLOCK/HUMAN_REVIEW.

    Convenience wrapper for routers that want to raise HTTP 403 automatically.
    """
    verdict = evaluate(action, value_aud_cents, context)
    if verdict.decision == AuthDecision.BLOCK:
        raise PolicyBlockedError(verdict)
    return verdict


class PolicyBlockedError(Exception):
    """Raised when the authority matrix issues a BLOCK decision."""

    def __init__(self, verdict: PolicyVerdict):
        self.verdict = verdict
        super().__init__(f"Policy BLOCK [{verdict.rule_id}]: {verdict.reason}")
