from __future__ import annotations

from typing import Any, Dict, List, Set


_STAGES = [
    "Reconnaissance",
    "Initial Access",
    "Persistence",
    "Execution",
    "Exfiltration",
    "Lateral Movement",
]


def _signal_set(verdict: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for i in (verdict.get("indicators") or []):
        t = str((i or {}).get("type") or "").strip().lower()
        if t:
            out.add(t)
    for r in (verdict.get("reasons") or []):
        rr = str(r or "").strip().lower()
        if rr:
            out.add(rr)
    return out


def infer_bec_kill_chain(email: Dict[str, Any], verdict: Dict[str, Any]) -> Dict[str, Any]:
    s = _signal_set(verdict)
    stages: List[str] = []

    if s & {
        "lookalike_domain",
        "confusable_homoglyph_domain",
        "vendor_homoglyph_impersonation",
        "message_id_reuse_detected",
    }:
        stages.append("Reconnaissance")

    if s & {
        "prompt_injection",
        "dangerous_tool_intent",
        "phishing_landing_page_high_risk",
        "phishing_landing_page_review",
        "reply_chain_hijack",
    }:
        stages.append("Initial Access")

    if s & {
        "mailbox_forwarding_rule_external",
        "mailbox_stealth_rule",
        "mailbox_delegate_added",
        "mailbox_oauth_high_privilege_consent",
    }:
        stages.append("Persistence")

    body_text = str(email.get("body") or "").lower()
    if s & {"vendor_domain_mismatch", "payment_term_anomaly"} or any(tok in body_text for tok in ("wire transfer", "bank account", "payment instruction", "invoice")):
        stages.append("Execution")

    if s & {"data_exfil_intent", "mailbox_mass_access"}:
        stages.append("Exfiltration")

    if s & {"mailbox_delegate_added", "mailbox_oauth_high_privilege_consent"}:
        stages.append("Lateral Movement")

    deduped = []
    seen = set()
    for st in stages:
        if st not in seen:
            deduped.append(st)
            seen.add(st)
    stage = deduped[-1] if deduped else "Reconnaissance"
    confidence = round(min(1.0, 0.3 + (0.12 * len(deduped))), 4)

    return {
        "stage": stage,
        "stages": deduped or ["Reconnaissance"],
        "attack_flow": [st for st in _STAGES if st in (deduped or {"Reconnaissance"})],
        "confidence": confidence,
        "signal_count": len(s),
    }

