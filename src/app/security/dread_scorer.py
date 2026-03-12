"""Dynamic per-event DREAD scoring with evidence trails and kill-chain binding.

Instead of returning a fixed average from static weights, each DREAD
component is derived from the detected signals, severity, and actor
context of the current event.

DREAD components (0-10 scale each):
    D — Damage:          How bad would successful exploitation be?
    R — Reproducibility:  How reliably can the attack be repeated?
    E — Exploitability:   How easy is it to launch the attack?
    A — Affected Users:   What proportion of users are impacted?
    D — Discoverability:  How easy is the vulnerability to find?

Each component includes an ``evidence`` list — the exact signals, MITRE
techniques, OWASP tags and kill-chain stages that drove the score.  This
gives auditors/investors a full trace from number to source.

The ``kill_chain_stage`` is inferred from the signal mix and used to
compute a **stage-weighted average** so that the same raw scores produce
different risk at different attack phases.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


# ── Signal → framework tag mappings (for evidence items) ──
_SIGNAL_MITRE: Dict[str, str] = {
    "prompt_injection": "AML.T0051",
    "jailbreak": "AML.T0054",
    "data_exfiltration": "T1041",
    "pci": "T1005",
    "pii": "T1005",
    "agentic_tool_abuse": "AML.T0040",
    "unexpected_code_exec": "T1059",
    "training_poisoning": "AML.T0020",
    "supply_chain": "T1195",
    "identity_abuse": "T1078",
    "social_engineering": "T1566",
    "unicode_obfuscation": "T1036",
    "embedding_weakness": "AML.T0043",
    "scanner_burst": "T1595",
    "cascading_failure": "T1499",
    "model_dos": "T1499",
}

_SIGNAL_OWASP: Dict[str, str] = {
    "prompt_injection": "LLM01:PromptInjection",
    "jailbreak": "LLM01:PromptInjection",
    "data_exfiltration": "LLM06:SensitiveInfoDisclosure",
    "pci": "LLM06:SensitiveInfoDisclosure",
    "pii": "LLM06:SensitiveInfoDisclosure",
    "agentic_tool_abuse": "LLM08:ExcessiveAgency",
    "training_poisoning": "LLM03:TrainingDataPoisoning",
    "supply_chain": "LLM05:SupplyChainVulnerabilities",
}

_CV_SIGNAL_MITRE: Dict[str, str] = {
    "qr_prompt_injection": "AML.T0051",
    "ocr_prompt_injection": "AML.T0051",
    "adversarial_detected": "AML.T0043",
    "cross_modal_mismatch": "AML.T0043",
    "ocr_yolo_label_conflict": "AML.T0015",
    "vision_yolo_conflict": "AML.T0015",
    "product_identity_low_confidence": "AML.T0043",
    "multimodal_attack_surface_high": "AML.T0051",
    "steg_suspicious": "T1027",
    "qr_code_detected": "T1566",
    "qr_external_url_detected": "T1566.002",
    "qr_external_url": "T1566.002",
    "payment_social_engineering": "AML.T0051",
    "pci_card_exposed": "T1005",
    "crypto_payment_uri": "AML.T0051",
    "ransomware_indicator": "AML.T0051",
    "qr_payload_vcard": "AML.T0048",
    "qr_payload_wifi": "AML.T0048",
    "qr_multi_mismatch": "AML.T0048",
    "qr_label_destination_mismatch": "AML.T0048",
    "unicode_obfuscation": "T1036",
    "encoded_payload_detected": "AML.T0051",
    "homoglyph_injection": "AML.T0051",
    "polyglot_suspected": "AML.T0048",
    "exif_text_injection": "AML.T0051",
    "cross_image_split_injection": "AML.T0051",
    "agentic_tool_injection": "AML.T0051",
    "agentic_tool_abuse": "AML.T0040",
}

_CV_SIGNAL_OWASP: Dict[str, str] = {
    "qr_prompt_injection": "LLM01:PromptInjection",
    "ocr_prompt_injection": "LLM01:PromptInjection",
    "adversarial_detected": "LLM02:InsecureOutputHandling",
    "cross_modal_mismatch": "LLM02:InsecureOutputHandling",
    "ocr_yolo_label_conflict": "LLM02:InsecureOutputHandling",
    "vision_yolo_conflict": "LLM02:InsecureOutputHandling",
    "product_identity_low_confidence": "LLM02:InsecureOutputHandling",
    "multimodal_attack_surface_high": "LLM01:PromptInjection",
    "payment_social_engineering": "LLM01:PromptInjection",
    "qr_external_url_detected": "LLM01:PromptInjection",
    "qr_external_url": "LLM01:PromptInjection",
    "pci_card_exposed": "LLM06:SensitiveInfoDisclosure",
    "crypto_payment_uri": "LLM02:InsecureOutputHandling",
    "ransomware_indicator": "LLM01:PromptInjection",
    "qr_payload_vcard": "LLM05:SupplyChainVulnerabilities",
    "qr_payload_wifi": "LLM05:SupplyChainVulnerabilities",
    "qr_multi_mismatch": "LLM05:SupplyChainVulnerabilities",
    "qr_label_destination_mismatch": "LLM05:SupplyChainVulnerabilities",
    "encoded_payload_detected": "LLM01:PromptInjection",
    "homoglyph_injection": "LLM01:PromptInjection",
    "polyglot_suspected": "LLM05:SupplyChainVulnerabilities",
    "exif_text_injection": "LLM01:PromptInjection",
    "cross_image_split_injection": "LLM01:PromptInjection",
    "agentic_tool_injection": "LLM01:PromptInjection",
    "agentic_tool_abuse": "LLM08:ExcessiveAgency",
}

# ── Kill-chain stage inference ──
_KILL_CHAIN_ORDER = [
    "Reconnaissance",
    "Weaponization",
    "Delivery",
    "Exploitation",
    "Installation",
    "CommandAndControl",
    "ActionsOnObjectives",
]

_SIGNAL_KILL_CHAIN: Dict[str, str] = {
    "scanner_burst": "Reconnaissance",
    "rate_anomaly": "Reconnaissance",
    "ip_risk": "Reconnaissance",
    "social_engineering": "Delivery",
    "identity_abuse": "Delivery",
    "prompt_injection": "Exploitation",
    "jailbreak": "Exploitation",
    "unicode_obfuscation": "Exploitation",
    "agentic_tool_abuse": "Installation",
    "unexpected_code_exec": "Installation",
    "training_poisoning": "Installation",
    "supply_chain": "Installation",
    "embedding_weakness": "Exploitation",
    "cross_modal_mismatch": "Exploitation",
    "ocr_yolo_label_conflict": "Delivery",
    "vision_yolo_conflict": "Delivery",
    "product_identity_low_confidence": "Reconnaissance",
    "multimodal_attack_surface_high": "Installation",
    "payment_social_engineering": "Delivery",
    "qr_external_url_detected": "Delivery",
    "qr_external_url": "Delivery",
    "crypto_payment_uri": "Delivery",
    "qr_payload_vcard": "Delivery",
    "qr_payload_wifi": "Delivery",
    "qr_multi_mismatch": "Delivery",
    "qr_label_destination_mismatch": "Delivery",
    "encoded_payload_detected": "Exploitation",
    "homoglyph_injection": "Exploitation",
    "cross_image_split_injection": "Exploitation",
    "agentic_tool_injection": "Exploitation",
    "agentic_tool_abuse": "Installation",
    "polyglot_suspected": "Weaponization",
    "exif_text_injection": "Exploitation",
    "ransomware_indicator": "ActionsOnObjectives",
    "pci_card_exposed": "ActionsOnObjectives",
    "email_c2_beaconing": "CommandAndControl",
    "data_exfiltration": "ActionsOnObjectives",
    "pci": "ActionsOnObjectives",
    "pii": "ActionsOnObjectives",
    "cascading_failure": "ActionsOnObjectives",
    "model_dos": "ActionsOnObjectives",
}

# ── Stage-weighted DREAD component weights (D, R, E, A, Disc.) ──
_STAGE_WEIGHTS: Dict[str, Tuple[float, float, float, float, float]] = {
    "Reconnaissance":       (1, 2, 2, 1, 3),
    "Weaponization":        (2, 2, 2, 1, 2),
    "Delivery":             (2, 2, 3, 1, 2),
    "Exploitation":         (3, 2, 3, 2, 1),
    "Installation":         (3, 2, 2, 3, 1),
    "CommandAndControl":    (3, 2, 2, 3, 1),
    "ActionsOnObjectives":  (3, 1, 1, 3, 1),
}


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def _evidence_item(signal: str, component: str, contribution: float, *, cv: bool = False) -> Dict[str, Any]:
    mitre_map = _CV_SIGNAL_MITRE if cv else _SIGNAL_MITRE
    owasp_map = _CV_SIGNAL_OWASP if cv else _SIGNAL_OWASP
    kc = _SIGNAL_KILL_CHAIN.get(signal, "")
    return {
        "signal": signal,
        "component": component,
        "contribution": round(contribution, 2),
        "mitre": mitre_map.get(signal, ""),
        "owasp": owasp_map.get(signal, ""),
        "kill_chain": kc,
        "source": "cv" if cv else "text",
    }


def infer_kill_chain_stage(signals: Dict[str, bool], cv_signals: Dict[str, Any] | None = None) -> str:
    """Pick the most advanced kill-chain stage reached by any active signal."""
    best_idx = -1
    for sig, active in signals.items():
        if not active:
            continue
        stage = _SIGNAL_KILL_CHAIN.get(sig)
        if stage and stage in _KILL_CHAIN_ORDER:
            idx = _KILL_CHAIN_ORDER.index(stage)
            if idx > best_idx:
                best_idx = idx
    for sig, active in (cv_signals or {}).items():
        if not active:
            continue
        stage = _SIGNAL_KILL_CHAIN.get(sig)
        if stage and stage in _KILL_CHAIN_ORDER:
            idx = _KILL_CHAIN_ORDER.index(stage)
            if idx > best_idx:
                best_idx = idx
    if best_idx < 0:
        return "Reconnaissance"  # default: earliest stage
    return _KILL_CHAIN_ORDER[best_idx]


def _weighted_avg(
    damage: float,
    reproducibility: float,
    exploitability: float,
    affected_users: float,
    discoverability: float,
    stage: str,
) -> float:
    """Stage-weighted DREAD average."""
    wD, wR, wE, wA, wDisc = _STAGE_WEIGHTS.get(stage, (2, 2, 2, 2, 2))
    total_w = wD + wR + wE + wA + wDisc
    return round(
        (wD * damage + wR * reproducibility + wE * exploitability + wA * affected_users + wDisc * discoverability)
        / total_w,
        2,
    )


def compute_dread(
    signals: Dict[str, bool],
    cv_signals: Dict[str, Any] | None = None,
    severity: str = "info",
    actor_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return per-event DREAD scores (0-10), evidence trails, kill-chain binding and weighted avg."""
    cv = cv_signals or {}
    actor = actor_context or {}
    sev = (severity or "info").lower()
    evidence: List[Dict[str, Any]] = []

    # Count how many distinct signals fired
    fired = sum(1 for v in signals.values() if v)
    cv_fired = sum(1 for v in cv.values() if v)
    total_fired = fired + cv_fired

    # ── Damage ──
    damage_base = {"critical": 9.5, "error": 9.0, "high": 7.5, "warn": 4.5, "info": 2.0}.get(sev, 2.0)
    evidence.append({"signal": f"severity:{sev}", "component": "damage", "contribution": damage_base, "mitre": "", "owasp": "", "kill_chain": "", "source": "severity"})
    if signals.get("data_exfiltration") or signals.get("pci"):
        bump = 2.0
        damage_base = _clamp(damage_base + bump)
        for s in ("data_exfiltration", "pci"):
            if signals.get(s):
                evidence.append(_evidence_item(s, "damage", bump))
    if signals.get("pii"):
        bump = 1.0
        damage_base = _clamp(damage_base + bump)
        evidence.append(_evidence_item("pii", "damage", bump))
    if signals.get("agentic_tool_abuse") or signals.get("unexpected_code_exec"):
        bump = 1.5
        damage_base = _clamp(damage_base + bump)
        for s in ("agentic_tool_abuse", "unexpected_code_exec"):
            if signals.get(s):
                evidence.append(_evidence_item(s, "damage", bump))
    damage = _clamp(damage_base)

    # ── Reproducibility ──
    repro_base = 3.0
    if total_fired >= 5:
        repro_base = 9.0
    elif total_fired >= 3:
        repro_base = 7.0
    elif total_fired >= 1:
        repro_base = 5.0
    evidence.append({"signal": f"signal_count:{total_fired}", "component": "reproducibility", "contribution": repro_base, "mitre": "", "owasp": "", "kill_chain": "", "source": "heuristic"})
    if signals.get("prompt_injection") or signals.get("jailbreak"):
        bump = 2.0
        repro_base = _clamp(repro_base + bump)
        for s in ("prompt_injection", "jailbreak"):
            if signals.get(s):
                evidence.append(_evidence_item(s, "reproducibility", bump))
    reproducibility = _clamp(repro_base)

    # ── Exploitability ──
    exploit_base = 3.0
    exploit_driver = ""
    if signals.get("prompt_injection"):
        exploit_base = 9.0
        exploit_driver = "prompt_injection"
    elif signals.get("jailbreak"):
        exploit_base = 8.5
        exploit_driver = "jailbreak"
    elif signals.get("identity_abuse") or signals.get("social_engineering"):
        exploit_base = 7.0
        exploit_driver = "identity_abuse" if signals.get("identity_abuse") else "social_engineering"
    elif signals.get("unicode_obfuscation"):
        exploit_base = 6.5
        exploit_driver = "unicode_obfuscation"
    elif signals.get("training_poisoning") or signals.get("supply_chain"):
        exploit_base = 4.0
        exploit_driver = "training_poisoning" if signals.get("training_poisoning") else "supply_chain"
    if exploit_driver:
        evidence.append(_evidence_item(exploit_driver, "exploitability", exploit_base))
    if cv.get("qr_prompt_injection") or cv.get("ocr_prompt_injection"):
        bump = 1.5
        exploit_base = _clamp(exploit_base + bump)
        for s in ("qr_prompt_injection", "ocr_prompt_injection"):
            if cv.get(s):
                evidence.append(_evidence_item(s, "exploitability", bump, cv=True))
    if cv.get("adversarial_detected"):
        bump = 1.0
        exploit_base = _clamp(exploit_base + bump)
        evidence.append(_evidence_item("adversarial_detected", "exploitability", bump, cv=True))
    if cv.get("cross_modal_mismatch") or cv.get("ocr_yolo_label_conflict") or cv.get("vision_yolo_conflict"):
        bump = 1.2
        exploit_base = _clamp(exploit_base + bump)
        if cv.get("cross_modal_mismatch"):
            evidence.append(_evidence_item("cross_modal_mismatch", "exploitability", bump, cv=True))
        if cv.get("ocr_yolo_label_conflict"):
            evidence.append(_evidence_item("ocr_yolo_label_conflict", "exploitability", bump, cv=True))
        if cv.get("vision_yolo_conflict"):
            evidence.append(_evidence_item("vision_yolo_conflict", "exploitability", bump, cv=True))
    if cv.get("multimodal_attack_surface_high"):
        bump = 1.6
        exploit_base = _clamp(exploit_base + bump)
        evidence.append(_evidence_item("multimodal_attack_surface_high", "exploitability", bump, cv=True))
    exploitability = _clamp(exploit_base)

    # ── Affected Users ──
    affected_base = 3.0
    role = str(actor.get("actor_role") or "").lower()
    if role in ("admin", "superuser", "owner"):
        affected_base = 8.0
        evidence.append({"signal": f"actor_role:{role}", "component": "affected_users", "contribution": 8.0, "mitre": "T1078", "owasp": "", "kill_chain": "", "source": "context"})
    elif role in ("merchant",):
        affected_base = 6.0
        evidence.append({"signal": f"actor_role:{role}", "component": "affected_users", "contribution": 6.0, "mitre": "", "owasp": "", "kill_chain": "", "source": "context"})
    if signals.get("data_exfiltration") or signals.get("pci"):
        bump = 2.0
        affected_base = _clamp(affected_base + bump)
        for s in ("data_exfiltration", "pci"):
            if signals.get(s):
                evidence.append(_evidence_item(s, "affected_users", bump))
    if signals.get("cascading_failure"):
        bump = 2.0
        affected_base = _clamp(affected_base + bump)
        evidence.append(_evidence_item("cascading_failure", "affected_users", bump))
    if signals.get("model_dos"):
        bump = 1.5
        affected_base = _clamp(affected_base + bump)
        evidence.append(_evidence_item("model_dos", "affected_users", bump))
    if cv.get("multimodal_attack_surface_high"):
        bump = 1.3
        affected_base = _clamp(affected_base + bump)
        evidence.append(_evidence_item("multimodal_attack_surface_high", "affected_users", bump, cv=True))
    affected_users = _clamp(affected_base)

    # ── Discoverability ──
    discover_base = 5.0
    discover_driver = ""
    if signals.get("prompt_injection") or signals.get("jailbreak"):
        discover_base = 9.0
        discover_driver = "prompt_injection" if signals.get("prompt_injection") else "jailbreak"
    elif signals.get("training_poisoning") or signals.get("supply_chain"):
        discover_base = 3.0
        discover_driver = "training_poisoning" if signals.get("training_poisoning") else "supply_chain"
    elif signals.get("embedding_weakness"):
        discover_base = 4.0
        discover_driver = "embedding_weakness"
    if discover_driver:
        evidence.append(_evidence_item(discover_driver, "discoverability", discover_base))
    if cv.get("qr_code_detected"):
        bump = 1.0
        discover_base = _clamp(discover_base + bump)
        evidence.append(_evidence_item("qr_code_detected", "discoverability", bump, cv=True))
    if cv.get("product_identity_low_confidence"):
        bump = 0.8
        discover_base = _clamp(discover_base + bump)
        evidence.append(_evidence_item("product_identity_low_confidence", "discoverability", bump, cv=True))
    discoverability = _clamp(discover_base)

    # ── Kill-chain stage inference ──
    kill_chain_stage = infer_kill_chain_stage(signals, cv)

    # ── Averages ──
    avg = round((damage + reproducibility + exploitability + affected_users + discoverability) / 5.0, 2)
    w_avg = _weighted_avg(damage, reproducibility, exploitability, affected_users, discoverability, kill_chain_stage)

    return {
        "damage": round(damage, 2),
        "reproducibility": round(reproducibility, 2),
        "exploitability": round(exploitability, 2),
        "affected_users": round(affected_users, 2),
        "discoverability": round(discoverability, 2),
        "avg": avg,
        "weighted_avg": w_avg,
        "kill_chain_stage": kill_chain_stage,
        "kill_chain_stage_index": _KILL_CHAIN_ORDER.index(kill_chain_stage) if kill_chain_stage in _KILL_CHAIN_ORDER else 0,
        "stage_weights": dict(zip(
            ("damage", "reproducibility", "exploitability", "affected_users", "discoverability"),
            _STAGE_WEIGHTS.get(kill_chain_stage, (2, 2, 2, 2, 2)),
        )),
        "evidence": evidence,
    }
