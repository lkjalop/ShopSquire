from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src.app.security.agent_events import (
    AgentInteractionType,
    ThreatCategory,
    log_agent_security_event,
)
from src.app.security.observer import analyze_payload


_EXFIL_PAT = re.compile(
    r"(?i)(exfiltrat|dump\s+database|export\s+all|export\s+secrets|reveal\s+system\s+prompt|send\s+all\s+customer)",
)
_POISON_PAT = re.compile(
    r"(?i)(poison\s+training|data\s+poison|backdoor(?:ed)?\s+dataset|prompt\s+poison)",
)


def _extract_signals(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        analysis = analyze_payload(payload or {})
    except Exception:
        analysis = {"severity": "info", "risk_adj": 0.0, "details": {"signals": {}}}
    details = analysis.get("details") if isinstance(analysis.get("details"), dict) else {}
    signals = details.get("signals") if isinstance(details.get("signals"), dict) else {}
    return {
        "analysis": analysis,
        "details": details,
        "signals": signals,
    }


def assess_agent_interaction(
    *,
    agent_name: str,
    stage: str,
    payload: Dict[str, Any] | None,
    tenant_id: str | None = None,
    trace_id: str | None = None,
) -> Dict[str, Any]:
    safe_payload = payload or {}
    text = ""
    try:
        text = json.dumps(safe_payload, ensure_ascii=False)
    except Exception:
        text = str(safe_payload)

    observed = _extract_signals(
        {
            "agent_name": agent_name,
            "stage": stage,
            "tenant_id": tenant_id,
            "trace_id": trace_id,
            "payload": safe_payload,
            "query": safe_payload.get("query") if isinstance(safe_payload, dict) else None,
            "ocr_text": safe_payload.get("ocr_text") if isinstance(safe_payload, dict) else None,
        }
    )
    analysis = observed["analysis"]
    signals = observed["signals"]

    exfil = bool(signals.get("data_exfiltration")) or bool(_EXFIL_PAT.search(text))
    poison = bool(signals.get("training_poisoning") or signals.get("poisoning_attempt")) or bool(_POISON_PAT.search(text))
    prompt_inj = bool(signals.get("prompt_injection") or signals.get("cv_prompt_injection"))

    severity = str(analysis.get("severity") or "info").lower()
    risk_adj = float(analysis.get("risk_adj") or 0.0)
    mitre: List[str] = list((observed["details"].get("mitre_atlas") if isinstance(observed["details"], dict) else []) or [])
    if exfil:
        mitre.extend(["AML.T0048", "T1567"])
    if poison:
        mitre.extend(["AML.T0020", "T1195"])
    if prompt_inj:
        mitre.append("AML.T0043")

    action = "allow"
    reasons: List[str] = []
    if exfil or poison:
        action = "isolate"
        reasons.append("high_confidence_exfil_or_poison_signal")
    elif severity in ("high", "critical") or risk_adj >= 65:
        action = "review"
        reasons.append("observer_high_risk")

    if exfil:
        reasons.append("data_exfiltration_detected")
    if poison:
        reasons.append("poisoning_detected")
    if prompt_inj:
        reasons.append("prompt_injection_detected")

    requires_escalation = action in ("isolate", "review")
    event_sev = "critical" if action == "isolate" else ("high" if action == "review" else "info")
    threat_cat = None
    if exfil:
        threat_cat = ThreatCategory.data_exfiltration
    elif poison:
        threat_cat = ThreatCategory.supply_chain
    elif prompt_inj:
        threat_cat = ThreatCategory.prompt_injection

    try:
        log_agent_security_event(
            interaction_type=AgentInteractionType.inter_service_call,
            source=agent_name,
            destination=f"agent_guardrail:{stage}",
            threat_category=threat_cat,
            severity=event_sev,
            confidence=0.95 if action == "isolate" else (0.75 if action == "review" else 0.15),
            details={
                "action": action,
                "stage": stage,
                "reasons": reasons,
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "risk_adj": risk_adj,
                "mitre": sorted(list(dict.fromkeys(mitre))),
            },
            requires_escalation=requires_escalation,
            mitre_attack_ids=sorted(list(dict.fromkeys(mitre))),
            remediation_suggested="isolate_agent_and_route_to_security_review" if action == "isolate" else (
                "require_human_review" if action == "review" else None
            ),
        )
    except Exception:
        pass

    return {
        "agent": agent_name,
        "stage": stage,
        "action": action,
        "severity": event_sev,
        "requires_escalation": requires_escalation,
        "reasons": reasons,
        "risk_adj": round(risk_adj, 2),
        "mitre": sorted(list(dict.fromkeys(mitre))),
        "signals": {
            "data_exfiltration": bool(exfil),
            "poisoning": bool(poison),
            "prompt_injection": bool(prompt_inj),
        },
    }

