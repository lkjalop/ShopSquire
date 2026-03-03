from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import text as sql_text

from src.app.deps import security_sanitize
from src.app.config import get_settings, load_feature_flags
from src.app.models.db import get_engine
from src.app.observability.metrics import record_security_event


class AgentInteractionType(str, Enum):
    webhook_received = "webhook.received"
    mcp_tool_invoked = "mcp.tool.invoked"
    user_query = "user.query"
    admin_action = "admin.action"
    llm_api_call = "llm.api.call"
    payment_api_call = "payment.api.call"
    webhook_dispatched = "webhook.dispatched"
    saas_api_call = "saas.api.call"
    inter_service_call = "service.internal.call"
    background_job = "job.background"


class ThreatCategory(str, Enum):
    supply_chain = "supply_chain"
    credential_abuse = "credential_abuse"
    prompt_injection = "prompt_injection"
    data_exfiltration = "data_exfiltration"
    privilege_escalation = "privilege_escalation"
    webhook_spoofing = "webhook_spoofing"
    api_abuse = "api_abuse"
    anomalous_behavior = "anomalous_behavior"
    dead_drop = "dead_drop"  # M06: outbound C2 / dead-drop channel detection


@dataclass
class AgentSecurityEvent:
    event_id: str
    timestamp: str
    interaction_type: AgentInteractionType
    source: str
    destination: str
    threat_category: Optional[ThreatCategory]
    severity: str
    confidence: float
    details: Dict[str, Any]
    requires_escalation: bool
    mitre_attack_ids: list[str]
    remediation_suggested: Optional[str]


def _normalize_severity(severity: str) -> str:
    sev = (severity or "info").strip().lower()
    if sev in ("warning", "warn"):
        return "warn"
    if sev in ("critical", "high", "info"):
        return sev
    return "info"


def _to_verdict_score(confidence: float) -> int:
    try:
        return max(0, min(int(round(float(confidence) * 100)), 100))
    except Exception:
        return 0


def log_agent_security_event(
    interaction_type: AgentInteractionType,
    source: str,
    destination: str,
    threat_category: ThreatCategory | None = None,
    severity: str = "info",
    confidence: float = 0.3,
    details: Dict[str, Any] | None = None,
    requires_escalation: bool = False,
    mitre_attack_ids: list[str] | None = None,
    remediation_suggested: str | None = None,
) -> None:
    event = AgentSecurityEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
        interaction_type=interaction_type,
        source=source or "unknown",
        destination=destination or "unknown",
        threat_category=threat_category,
        severity=_normalize_severity(severity),
        confidence=float(confidence or 0.0),
        details=details or {},
        requires_escalation=bool(requires_escalation),
        mitre_attack_ids=mitre_attack_ids or [],
        remediation_suggested=remediation_suggested,
    )
    payload = {"agent_event": asdict(event)}
    sanitized = security_sanitize(payload)
    # Apply feature flags for persistence behavior
    flags = load_feature_flags(get_settings().feature_flags_path)
    persist_content = bool(flags.get("SECURITY_EVENT_PERSIST_CONTENT", False))
    verdict_score = _to_verdict_score(event.confidence)
    record_security_event(
        event_type=event.interaction_type.value,
        severity=event.severity,
        category=(event.threat_category.value if event.threat_category else "none"),
    )
    try:
        eng = get_engine()
        with eng.begin() as conn:
            conn.execute(
                sql_text(
                    "INSERT INTO security_events (id, path, event_time, severity, verdict_score, details) "
                    "VALUES (:id, :path, :event_time, :severity, :score, :details)"
                ),
                {
                    "id": event.event_id,
                    "path": event.destination,
                    "event_time": event.timestamp,
                    "severity": event.severity,
                    "score": verdict_score,
                    # When content persistence is disabled, keep only minimal agent_event fields
                    "details": json.dumps(
                        sanitized if persist_content else {
                            "agent_event": sanitized.get("agent_event"),
                            "payload": None,
                            "analysis": {},
                        },
                        ensure_ascii=False,
                    ),
                },
            )
    except Exception:
        # Do not block on logging failures.
        pass

    # Best-effort external telemetry emit (non-blocking)
    try:
        from src.app.security.telemetry_emit import emit_security_telemetry

        emit_security_telemetry(
            {
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "interaction_type": event.interaction_type.value,
                "source": event.source,
                "destination": event.destination,
                "threat_category": event.threat_category.value if event.threat_category else None,
                "severity": event.severity,
                "confidence": event.confidence,
                "requires_escalation": event.requires_escalation,
                "mitre_attack_ids": event.mitre_attack_ids,
                "remediation_suggested": event.remediation_suggested,
            }
        )
    except Exception:
        # Never raise on telemetry issues
        pass


def log_mcp_tool_invocation(
    tool_name: str,
    source: str,
    destination: str,
    details: Dict[str, Any] | None = None,
) -> None:
    """Helper for MCP tool calls; wire this in once tool execution exists."""
    log_agent_security_event(
        interaction_type=AgentInteractionType.mcp_tool_invoked,
        source=source,
        destination=destination or tool_name,
        threat_category=None,
        severity="info",
        confidence=0.2,
        details={"tool": tool_name, **(details or {})},
        requires_escalation=False,
    )
