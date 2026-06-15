"""Route enforcement seam for high-impact actions.

This is the single place where the legacy deterministic authority matrix
(action_authority_matrix) and the unified Authorization Engine
(security.authorization_engine) meet. Strategy (the consolidation path):

  1. The matrix stays AUTHORITATIVE by default — zero behaviour change, so the
     already-wired routers (refund, bank_change, supplier_pay, pii_export) are
     untouched in production.
  2. The engine runs in SHADOW alongside it on every call: it produces its own
     verdict, writes the control-plane audit (policy_evaluation_log etc.), emits
     the decision trace, and we record whether the two AGREE on allow-vs-block.
  3. Once the parity metric shows sustained agreement, flip
     ``AUTHZ_ENGINE_AUTHORITATIVE=1`` and the engine drives the 403/409 — the
     matrix becomes the shadow. That is the cutover from "two overlapping
     mechanisms" to "one provable gate", with data to justify it.

The external contract is preserved exactly: returns a ``PolicyVerdict`` on
allow; raises HTTP 403 on BLOCK and 409 on DUAL_CONTROL/HUMAN_REVIEW.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import HTTPException

from src.app.policy.action_authority_matrix import AuthDecision, PolicyVerdict, evaluate

_TRUE = {"1", "true", "yes", "on"}


def _engine_authoritative() -> bool:
    return str(os.getenv("AUTHZ_ENGINE_AUTHORITATIVE", "")).strip().lower() in _TRUE


def _run_engine_shadow(action: str, value_aud_cents: int, context: Optional[Dict[str, Any]]):
    """Best-effort engine evaluation alongside the matrix. Never raises; returns
    the AuthorizationDecision or None if the engine is unavailable."""
    try:
        from src.app.security.authorization_engine import authorize_action
        ctx = dict(context or {})
        return authorize_action(
            action,
            requester=str(ctx.get("requested_by_role") or "route_enforcement"),
            value_usd=float(value_aud_cents or 0) / 100.0,
            trace_id=ctx.get("trace_id"),
            subject_id=ctx.get("order_id") or ctx.get("uid") or ctx.get("subject_id"),
            metadata={"seam": "route_enforcement", "action_context": ctx},
            enforce_lane=False,  # human-authenticated seam — no agent lane to police
        )
    except Exception:
        return None


def _verdict_from_engine(decision) -> PolicyVerdict:
    """Translate an engine decision into a matrix PolicyVerdict for the
    authoritative cutover path. Conservative: any non-allow maps to a blocking
    decision (403 for hard/compromise, 409 for governance escalation)."""
    if decision.allowed:
        return PolicyVerdict(decision=AuthDecision.ALLOW, reason=decision.reason, rule_id="ENGINE")
    guardrails = decision.guardrails_tripped or []
    if "hard_block" in guardrails or decision.is_compromise:
        return PolicyVerdict(
            decision=AuthDecision.BLOCK,
            reason=decision.reason,
            rule_id="ENGINE",
            alert_siem=bool(decision.is_compromise),
            create_ticket=True,
            ticket_priority="critical",
        )
    # escalate_governance / never_auto / value-band → governance review (409)
    return PolicyVerdict(
        decision=AuthDecision.HUMAN_REVIEW,
        reason=decision.reason,
        rule_id="ENGINE",
        create_ticket=True,
        ticket_priority="high",
    )


def _record_parity(action: str, matrix_verdict: PolicyVerdict, decision) -> None:
    try:
        from src.app.observability.metrics import record_authz_parity
        agree = (matrix_verdict.decision == AuthDecision.ALLOW) == bool(decision.allowed)
        record_authz_parity(action, agree)
    except Exception:
        pass


def enforce_action_authority(
    action: str,
    *,
    value_aud_cents: int = 0,
    context: Dict[str, Any] | None = None,
) -> PolicyVerdict:
    matrix_verdict = evaluate(action, value_aud_cents=value_aud_cents, context=context)

    # Shadow the engine on every call (audit + parity), regardless of who's authoritative.
    decision = _run_engine_shadow(action, value_aud_cents, context)
    if decision is not None:
        _record_parity(action, matrix_verdict, decision)

    authoritative = (
        _verdict_from_engine(decision)
        if (_engine_authoritative() and decision is not None)
        else matrix_verdict
    )

    if authoritative.decision == AuthDecision.ALLOW:
        return authoritative

    detail = {
        "error": "policy_gate_denied",
        "action": action,
        "decision": str(authoritative.decision.value),
        "reason": authoritative.reason,
        "rule_id": authoritative.rule_id,
        "requires_2fa": bool(authoritative.requires_2fa),
        "create_ticket": bool(authoritative.create_ticket),
        "ticket_priority": authoritative.ticket_priority,
        "context": authoritative.context,
        "authority": "engine" if authoritative.rule_id == "ENGINE" else "matrix",
    }
    if decision is not None:
        detail["engine_shadow"] = {
            "decision": decision.decision,
            "terminal_outcome": decision.terminal_outcome,
            "residual": decision.residual,
        }
    if authoritative.decision == AuthDecision.BLOCK:
        raise HTTPException(status_code=403, detail=detail)
    raise HTTPException(status_code=409, detail=detail)
