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


def _shared_redis():
    """The REAL Redis (shared across uvicorn workers), or None. The DummyRedis dev fallback is NOT
    shared — it answers in-process — so it returns None here to force the per-worker deque path."""
    try:
        from src.app.deps import get_redis
        r = get_redis()
        return None if type(r).__name__ == "DummyRedis" else r
    except Exception:
        return None


def _add_and_count(store: "dict[str, Deque[Tuple[float, int]]]", ns: str, key: str,
                   amount_cents: int, now: float) -> Tuple[int, int]:
    """Record this attempt and return (recent_count, tiny_count) over the sliding window. Redis-backed
    (a ZSET per key, scored by timestamp, member '{ts}:{amount}') so velocity is SHARED across workers;
    the in-process deque is the fallback ONLY when Redis is down (then it degrades to per-worker, as
    before). Without this, multi-worker deployments count 1/N of a card-tester's attempts per worker
    and the velocity/card-testing thresholds never trip."""
    r = _shared_redis()
    if r is not None:
        try:
            zkey = f"payvel:{ns}:{key}"
            cutoff = now - _WINDOW_SECONDS
            r.zadd(zkey, {f"{now:.6f}:{int(amount_cents or 0)}": now})
            r.zremrangebyscore(zkey, 0, cutoff)
            r.expire(zkey, _WINDOW_SECONDS + 60)
            members = r.zrange(zkey, 0, -1) or []
            tiny = 0
            for m in members:
                try:
                    if int(str(m).rsplit(":", 1)[1]) <= 300:
                        tiny += 1
                except (ValueError, IndexError):
                    pass
            return len(members), tiny
        except Exception:
            pass  # fall through to the in-process window
    q = store[key]
    _trim(q, now)
    q.append((now, int(amount_cents or 0)))
    return len(q), sum(1 for _, v in q if v <= 300)


def reset_counters() -> None:
    """Clear the in-process velocity windows. For test isolation (these module-level counters
    otherwise accumulate across tests in one process and shift a classification order-dependently)
    and for an ops reset lever."""
    _UID_ATTEMPTS.clear()
    _IP_ATTEMPTS.clear()
    r = _shared_redis()
    if r is not None:
        try:
            keys = list(r.scan_iter("payvel:*")) if hasattr(r, "scan_iter") else []
            if keys:
                r.delete(*keys)
        except Exception:
            pass


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
    # Shared-across-workers velocity windows (Redis-backed; per-worker deque fallback when Redis down).
    recent_uid, tiny_uid = _add_and_count(_UID_ATTEMPTS, "uid", uid_key, amount_cents, now)
    recent_ip, _ = _add_and_count(_IP_ATTEMPTS, "ip", ip_key, amount_cents, now)
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

