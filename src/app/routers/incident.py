import time
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Depends

from src.app.security.pci import contains_pci_data
from src.app.config import load_feature_flags, get_settings
import json
import os
from src.app.observability.metrics import record_incident_alert, record_ticket
from src.app.observability.tracing import get_tracer
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER

router = APIRouter(prefix="/api/v1/incident", tags=["incident"])
tracer = get_tracer("incident-router")


def _route_threshold(topic: str) -> str:
    path = os.path.join("config", "security", "routing_policy.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            policy = json.load(f)
        topics = policy.get("topics", {})
        return topics.get(topic, {}).get("threshold", policy.get("defaults", {}).get("threshold", "p2"))
    except Exception:
        return "p2"


@router.post("/alert")
def send_alert(topic: str, message: str, severity: Optional[str] = None, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("incident.alert") as span:
        span.set_attribute("incident.topic", topic or "unknown")
        flags = load_feature_flags(get_settings().feature_flags_path)
        if flags.get("KILL_SWITCH"):
            raise HTTPException(status_code=503, detail="Agent disabled by kill switch")
        if contains_pci_data(message):
            raise HTTPException(status_code=400, detail="PCI-DSS sensitive data detected")
        # Stub connectors: pretend we sent to Slack/Discord/Teams
        severity_val = severity or _route_threshold(topic)
        record_incident_alert(topic, severity_val)
        return {
            "routed": True,
            "channels": ["slack", "discord", "teams"],
            "topic": topic,
            "severity": severity_val,
            "timestamp": int(time.time()),
        }


@router.post("/ticket")
def create_ticket(topic: str, title: str, description: str, priority: Optional[str] = None, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("incident.ticket") as span:
        span.set_attribute("incident.topic", topic or "unknown")
        flags = load_feature_flags(get_settings().feature_flags_path)
        if flags.get("KILL_SWITCH"):
            raise HTTPException(status_code=503, detail="Agent disabled by kill switch")
        if contains_pci_data(description):
            raise HTTPException(status_code=400, detail="PCI-DSS sensitive data detected")
        # Stub Jira creation
        priority_val = priority or _route_threshold(topic)
        record_ticket(topic, priority_val)
        return {
            "created": True,
            "system": "jira",
            "topic": topic,
            "priority": priority_val,
            "key": "JIRA-TEST-1",
        }


@router.post("/block")
def block_action(target: str, reason: str, severity: Optional[str] = None, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Hard-block endpoint for security incidents.

    This is a stub for integrating with WAF/IAM/etc. It records an incident and
    returns an acknowledgement payload for UI and automation.
    """
    with tracer.start_as_current_span("incident.block") as span:
        span.set_attribute("incident.target", target or "unknown")
        flags = load_feature_flags(get_settings().feature_flags_path)
        if flags.get("KILL_SWITCH"):
            raise HTTPException(status_code=503, detail="Agent disabled by kill switch")
        if contains_pci_data(reason):
            raise HTTPException(status_code=400, detail="PCI-DSS sensitive data detected")
        sev = severity or _route_threshold("security_block")
        record_incident_alert("security_block", sev)
        return {
            "blocked": True,
            "target": target,
            "reason": reason,
            "severity": sev,
            "timestamp": int(time.time()),
        }
