from __future__ import annotations

from typing import Any, Dict

from src.app.security.payment_threats import evaluate_payment_threat
from src.app.services.decision_log import log_trace_event


def evaluate_transaction_firewall(
    *,
    provider: str,
    uid: str,
    amount_cents: int,
    currency: str,
    description: str | None,
    request_ip: str | None,
    idempotency_key: str | None,
    tenant_id: str | None,
    trace_id: str | None = None,
    device_risk: float = 0.0,
    impossible_travel: bool = False,
    return_abuse_linked: bool = False,
    bin_country_mismatch: bool = False,
) -> Dict[str, Any]:
    base = evaluate_payment_threat(
        provider=provider,
        uid=uid,
        amount_cents=amount_cents,
        currency=currency,
        description=description,
        request_ip=request_ip,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
    )
    reasons = list(base.get("reasons") or [])
    score = float(base.get("score") or 0.0)
    if float(device_risk or 0.0) >= 0.7:
        score += 15.0
        reasons.append("device_risk_high")
    if impossible_travel:
        score += 20.0
        reasons.append("impossible_travel")
    if return_abuse_linked:
        score += 18.0
        reasons.append("return_abuse_linkage")
    if bin_country_mismatch:
        score += 14.0
        reasons.append("bin_country_mismatch")
    score = max(0.0, min(100.0, score))
    action = "allow"
    if score >= 92.0:
        action = "hard_block"
    elif score >= 75.0:
        action = "manual_review"
    elif score >= 55.0:
        action = "step_up_mfa"
    # Hard policy floor: explicit high-risk behavioral indicators should never auto-allow.
    if action == "allow" and impossible_travel and float(device_risk or 0.0) >= 0.7:
        action = "step_up_mfa"
    if action in ("allow", "step_up_mfa") and return_abuse_linked and bin_country_mismatch:
        action = "manual_review"
    out = {
        **base,
        "score": round(score, 2),
        "action": action,
        "reasons": reasons,
        "rule_pack": "transaction_firewall_v1",
    }
    if trace_id:
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="policy_gate",
                source_type="agent",
                source_id="Transaction_Firewall_Agent",
                target_type="payment",
                target_id=provider,
                payload={
                    "decision": action,
                    "score": out.get("score"),
                    "reason_codes": reasons,
                    "provider": provider,
                },
            )
        except Exception:
            pass
    return out
