from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from src.app.policy.action_authority_matrix import AuthDecision, PolicyVerdict, evaluate


def enforce_action_authority(
    action: str,
    *,
    value_aud_cents: int = 0,
    context: Dict[str, Any] | None = None,
) -> PolicyVerdict:
    verdict = evaluate(action, value_aud_cents=value_aud_cents, context=context)
    if verdict.decision == AuthDecision.ALLOW:
        return verdict
    detail = {
        "error": "policy_gate_denied",
        "action": action,
        "decision": str(verdict.decision.value),
        "reason": verdict.reason,
        "rule_id": verdict.rule_id,
        "requires_2fa": bool(verdict.requires_2fa),
        "create_ticket": bool(verdict.create_ticket),
        "ticket_priority": verdict.ticket_priority,
        "context": verdict.context,
    }
    if verdict.decision == AuthDecision.BLOCK:
        raise HTTPException(status_code=403, detail=detail)
    raise HTTPException(status_code=409, detail=detail)
