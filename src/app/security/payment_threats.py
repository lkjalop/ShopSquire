from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Tuple

from src.app.security.agent_events import (
    AgentInteractionType,
    ThreatCategory,
    log_agent_security_event,
)
from src.app.security.observer import analyze_payload


_UID_ATTEMPTS: dict[str, Deque[Tuple[float, int]]] = defaultdict(deque)
_IP_ATTEMPTS: dict[str, Deque[Tuple[float, int]]] = defaultdict(deque)
_WINDOW_SECONDS = 15 * 60

_SUSPICIOUS_DESC = re.compile(
    r"(?i)(stolen\s+card|card\s+testing|test\s+card|unauthori[sz]ed|bypass\s+3ds|chargeback\s+loop|dump\s+cvv)",
)


def _trim(q: Deque[Tuple[float, int]], now: float) -> None:
    while q and (now - q[0][0]) > _WINDOW_SECONDS:
        q.popleft()


def evaluate_payment_threat(
    *,
    provider: str,
    uid: str,
    amount_cents: int,
    currency: str,
    description: str | None,
    request_ip: str | None,
    idempotency_key: str | None,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    now = time.time()
    uid_key = str(uid or "unknown")
    ip_key = str(request_ip or "unknown")
    uid_q = _UID_ATTEMPTS[uid_key]
    ip_q = _IP_ATTEMPTS[ip_key]
    _trim(uid_q, now)
    _trim(ip_q, now)
    uid_q.append((now, int(amount_cents or 0)))
    ip_q.append((now, int(amount_cents or 0)))

    recent_uid = len(uid_q)
    recent_ip = len(ip_q)
    tiny_uid = sum(1 for _, v in uid_q if v <= 300)
    huge_amount = int(amount_cents or 0) >= 500000
    suspicious_desc = bool(_SUSPICIOUS_DESC.search(description or ""))

    observer = analyze_payload(
        {
            "provider": provider,
            "uid": uid_key,
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
            "ip": request_ip,
            "amount_cents": amount_cents,
            "currency": currency,
            "description": description or "",
            "channel": "payments",
        }
    )
    risk_adj = float(observer.get("risk_adj") or 0.0)
    sev = str(observer.get("severity") or "info").lower()
    details = observer.get("details") if isinstance(observer.get("details"), dict) else {}

    reasons: List[str] = []
    mitre = list(details.get("mitre_atlas") or [])
    if recent_uid >= 8:
        reasons.append("high_uid_velocity")
        mitre.append("T1110")
    if recent_ip >= 14:
        reasons.append("high_ip_velocity")
        mitre.append("T1498")
    if tiny_uid >= 6:
        reasons.append("possible_card_testing")
        mitre.append("T1659")
    if huge_amount:
        reasons.append("high_value_transaction")
    if suspicious_desc:
        reasons.append("suspicious_payment_description")
        mitre.extend(["T1078", "T1566"])
    if sev in ("high", "critical") or risk_adj >= 65:
        reasons.append("observer_high_risk")

    score = 0.0
    score += min(35.0, max(0.0, (recent_uid - 1) * 4.0))
    score += min(30.0, max(0.0, (recent_ip - 1) * 2.5))
    score += 25.0 if tiny_uid >= 6 else 0.0
    score += 25.0 if huge_amount else 0.0
    score += 35.0 if suspicious_desc else 0.0
    score += min(35.0, risk_adj * 0.35)

    decision = "allow"
    severity = "info"
    if suspicious_desc or score >= 90:
        decision = "block"
        severity = "critical"
    elif score >= 55 or sev in ("high", "critical"):
        decision = "review"
        severity = "high"

    try:
        log_agent_security_event(
            interaction_type=AgentInteractionType.payment_api_call,
            source="payment_guardrail",
            destination=provider,
            threat_category=ThreatCategory.api_abuse if decision == "block" else (
                ThreatCategory.anomalous_behavior if decision == "review" else None
            ),
            severity=severity,
            confidence=0.95 if decision == "block" else (0.75 if decision == "review" else 0.1),
            details={
                "decision": decision,
                "score": round(score, 2),
                "reasons": reasons,
                "uid_attempts_15m": recent_uid,
                "ip_attempts_15m": recent_ip,
                "tiny_amount_attempts_15m": tiny_uid,
                "provider": provider,
                "amount_cents": amount_cents,
            },
            requires_escalation=decision in ("review", "block"),
            mitre_attack_ids=sorted(list(dict.fromkeys(mitre))),
            remediation_suggested="block_and_escalate_payments_soc" if decision == "block" else (
                "step_up_auth_or_manual_review" if decision == "review" else None
            ),
        )
    except Exception:
        pass

    return {
        "decision": decision,
        "severity": severity,
        "score": round(score, 2),
        "reasons": reasons,
        "mitre": sorted(list(dict.fromkeys(mitre))),
        "requires_escalation": decision in ("review", "block"),
        "telemetry": {
            "uid_attempts_15m": recent_uid,
            "ip_attempts_15m": recent_ip,
            "tiny_amount_attempts_15m": tiny_uid,
            "risk_adj": round(risk_adj, 2),
        },
    }

