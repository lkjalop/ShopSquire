from __future__ import annotations

from typing import Any, Dict

from src.app.deps import scrub_pii


def image_security_event(
    *,
    sec_signals: Dict[str, Any],
    frameworks: Dict[str, Any],
    severity: str,
    policy_route: str,
    uid: str | None,
    query: str | None,
    trace_id: str | None,
) -> Dict[str, Any] | None:
    """Build a Security Observer event for a flagged image."""
    if not policy_route or str(policy_route).lower() == "allow":
        return None
    verdict = (
        "block"
        if policy_route == "lockdown"
        else "escalate"
        if policy_route == "escalate"
        else "sanitize"
    )
    signals = {key: bool(value) for key, value in (sec_signals or {}).items()}
    framework = frameworks or {}
    return {
        "payload": {
            "uid": uid,
            "query": scrub_pii(query or ""),
            "trace_id": trace_id,
            "event_ref": f"image_security:{trace_id}",
            "cv_signals": signals,
        },
        "analysis": {
            "signals": {key: True for key, value in signals.items() if value},
            "cv_signals": signals,
            "severity": severity,
            "route": policy_route,
            "verdict": verdict,
            "mitre_atlas": framework.get("mitre_atlas") or [],
            "mitre_attack": framework.get("mitre_attack") or [],
            "owasp_llm_top10": framework.get("owasp_llm_top10") or [],
            "stride_categories": framework.get("stride_categories") or [],
            "dread": framework.get("dread") or {},
            "cvss": framework.get("cvss") or {},
        },
    }
