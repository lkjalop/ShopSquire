from __future__ import annotations

import json
import time
import uuid
from typing import Dict, Optional

from sqlalchemy import text as sql_text

from src.app.deps import get_redis
from src.app.models.db import get_engine
from src.app.security.agent_events import AgentInteractionType, ThreatCategory, log_agent_security_event


FAIL_WINDOW = 10 * 60
FAIL_THRESHOLD = 5


def log_iam_event(event_type: str, actor: str, source_ip: str, user_agent: str, success: bool, details: Dict | None = None):
    eng = get_engine()
    payload = json.dumps(details or {}, ensure_ascii=False)
    with eng.begin() as conn:
        conn.execute(
            sql_text(
                "INSERT INTO iam_events (id, event_type, actor, source_ip, user_agent, success, risk_score, details) "
                "VALUES (:id, :event_type, :actor, :source_ip, :user_agent, :success, :risk_score, :details)"
            ),
            {
                "id": str(uuid.uuid4()),
                "event_type": event_type,
                "actor": actor,
                "source_ip": source_ip,
                "user_agent": user_agent,
                "success": 1 if success else 0,
                "risk_score": 0,
                "details": payload,
            },
        )


def check_bruteforce(actor: str) -> Optional[str]:
    redis = get_redis()
    key = f"iam:fail:{actor}"
    try:
        count = redis.incrby(key, 1)
        redis.expire(key, FAIL_WINDOW)
        if count >= FAIL_THRESHOLD:
            return "bruteforce_suspected"
    except Exception:
        pass
    return None


def check_impossible_travel(actor: str, source_ip: str) -> Optional[str]:
    redis = get_redis()
    key = f"iam:last:{actor}"
    try:
        raw = redis.get(key)
        now = int(time.time())
        if raw:
            prev = json.loads(raw)
            last_ip = prev.get("ip")
            last_ts = int(prev.get("ts") or 0)
            if last_ip and last_ip != source_ip and (now - last_ts) < 3600:
                return "impossible_travel"
        redis.setex(key, 86400, json.dumps({"ip": source_ip, "ts": now}))
    except Exception:
        pass
    return None


def emit_iam_anomaly(actor: str, source_ip: str, reason: str):
    log_agent_security_event(
        interaction_type=AgentInteractionType.admin_action,
        source=source_ip,
        destination="iam",
        threat_category=ThreatCategory.credential_abuse,
        severity="warn",
        confidence=0.6,
        details={"actor": actor, "reason": reason},
        requires_escalation=False,
    )
