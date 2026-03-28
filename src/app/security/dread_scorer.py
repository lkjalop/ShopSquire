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
# MITRE ATT&CK + ATLAS (AML.*) mappings — expanded to cover fraud, agentic AI,
# network-based, and insider-threat signal categories (Oct 2025 ATLAS additions included).
_SIGNAL_MITRE: Dict[str, str] = {
    # ── Prompt / Agentic AI (MITRE ATLAS) ──
    "prompt_injection": "AML.T0051",
    "jailbreak": "AML.T0054",
    "agentic_tool_abuse": "AML.T0040",
    "training_poisoning": "AML.T0020",
    "embedding_weakness": "AML.T0043",
    "context_poisoning": "AML.T0056",       # ATLAS Oct 2025: context window manipulation
    "memory_manipulation": "AML.T0057",     # ATLAS Oct 2025: long-term memory injection
    "rag_credential_harvesting": "AML.T0058", # ATLAS Oct 2025: RAG pipeline exfil
    "agent_goal_hijacking": "AML.T0040",
    "tool_output_spoofing": "AML.T0040",
    "model_inversion": "AML.T0024",         # Reconstruct training data
    "model_extraction": "AML.T0025",        # Steal model parameters via query API
    "indirect_prompt_injection": "AML.T0051.001",  # Injected via retrieved doc/URL
    # ── Code / Execution ──
    "unexpected_code_exec": "T1059",
    "supply_chain": "T1195",
    "supply_chain_software": "T1195.002",
    "supply_chain_dependency": "T1195.001",
    "malicious_script_injection": "T1059.007",  # JavaScript injection
    "file_format_abuse": "T1204.002",
    # ── Credential / Identity ──
    "identity_abuse": "T1078",
    "account_takeover": "T1078.003",
    "credential_stuffing": "T1110.004",
    "brute_force": "T1110",
    "social_engineering": "T1566",
    "phishing": "T1566.001",
    "spear_phishing_link": "T1566.002",
    "session_hijack_indicators": "T1563",
    "session_fixation": "T1563.001",
    # ── Data / Exfiltration ──
    "data_exfiltration": "T1041",
    "pci": "T1005",
    "pii": "T1005",
    "sensitive_data_exposure": "T1005",
    "api_data_scraping": "T1213",
    "email_c2_beaconing": "T1071.003",
    # ── Obfuscation / Evasion ──
    "unicode_obfuscation": "T1036",
    "encoded_payload": "T1027",
    "steganography": "T1027.003",
    "log_tampering": "T1070",
    "timestomping": "T1070.006",
    # ── Network / Discovery ──
    "scanner_burst": "T1595",
    "active_scanning": "T1595.001",
    "ip_velocity_spike": "T1595.002",
    "rate_anomaly": "T1595",
    "port_scan": "T1046",
    "ip_risk": "T1090",         # Proxy / anonymization
    "asn_known_proxy_tor": "T1090.003",
    "geoip_high_risk_country": "T1090.002",
    # ── Fraud-specific (mapped to closest ATT&CK techniques) ──
    "serial_mismatch": "T1036.001",     # Masquerading: invalid identifier
    "image_hash_match_fraud_db": "T1036",
    "return_pattern_abuse": "T1078.002",  # Valid accounts: abusing legitimate account
    "chargeback_history": "T1657",      # Financial theft
    "coupon_stacking_attempt": "T1657",
    "price_manipulation_attempt": "T1565.001",  # Data manipulation
    "product_category_mismatch": "T1036",
    "geographic_anomaly": "T1090",
    "gnn_ring_risk_high": "T1078.004",  # Cloud accounts / fraud ring
    # ── Availability / DoS ──
    "cascading_failure": "T1499",
    "model_dos": "T1499",
    "resource_exhaustion": "T1499.004",
    # ── Insider Threat / Privilege ──
    "insider_threat_signal": "T1078.001",
    "privilege_escalation_attempt": "T1548",
    "lateral_movement_indicator": "T1021",
}

_SIGNAL_OWASP: Dict[str, str] = {
    # OWASP LLM Top 10 2025
    "prompt_injection": "LLM01:PromptInjection",
    "indirect_prompt_injection": "LLM01:PromptInjection",
    "jailbreak": "LLM01:PromptInjection",
    "context_poisoning": "LLM01:PromptInjection",
    "memory_manipulation": "LLM01:PromptInjection",
    "tool_output_spoofing": "LLM02:InsecureOutputHandling",
    "unexpected_code_exec": "LLM02:InsecureOutputHandling",
    "training_poisoning": "LLM03:TrainingDataPoisoning",
    "model_inversion": "LLM03:TrainingDataPoisoning",
    "supply_chain": "LLM05:SupplyChainVulnerabilities",
    "supply_chain_dependency": "LLM05:SupplyChainVulnerabilities",
    "rag_credential_harvesting": "LLM05:SupplyChainVulnerabilities",
    "data_exfiltration": "LLM06:SensitiveInfoDisclosure",
    "pci": "LLM06:SensitiveInfoDisclosure",
    "pii": "LLM06:SensitiveInfoDisclosure",
    "sensitive_data_exposure": "LLM06:SensitiveInfoDisclosure",
    "api_data_scraping": "LLM06:SensitiveInfoDisclosure",
    "identity_abuse": "LLM07:InsecurePluginDesign",
    "agentic_tool_abuse": "LLM08:ExcessiveAgency",
    "agent_goal_hijacking": "LLM08:ExcessiveAgency",
    "model_extraction": "LLM09:Overreliance",
    "embedding_weakness": "LLM09:Overreliance",
    # OWASP Agentic AI Top 10 Dec 2025
    "agent_goal_hijacking": "AgentAI01:GoalHijacking",
    "context_poisoning": "AgentAI02:ContextPoisoning",
    "memory_manipulation": "AgentAI03:MemoryManipulation",
    "rag_credential_harvesting": "AgentAI04:RAGDataExfil",
    "cascading_failure": "AgentAI05:CascadingFailure",
    "model_dos": "AgentAI05:CascadingFailure",
    "insider_threat_signal": "AgentAI07:InsiderThreat",
    "privilege_escalation_attempt": "AgentAI08:PrivilegeEscalation",
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
    "steg_score_elevated": "T1027",
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
    "steg_score_elevated": "LLM02:InsecureOutputHandling",
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
    "steg_score_elevated": "Weaponization",
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
    "sensitive_data_exposure": "ActionsOnObjectives",
    "cascading_failure": "ActionsOnObjectives",
    "model_dos": "ActionsOnObjectives",
    "resource_exhaustion": "ActionsOnObjectives",
    # New Oct 2025 ATLAS additions
    "context_poisoning": "Exploitation",
    "memory_manipulation": "Exploitation",
    "rag_credential_harvesting": "ActionsOnObjectives",
    "agent_goal_hijacking": "Installation",
    "tool_output_spoofing": "Exploitation",
    "indirect_prompt_injection": "Exploitation",
    "model_inversion": "ActionsOnObjectives",
    "model_extraction": "Reconnaissance",
    # Fraud signals
    "serial_mismatch": "Delivery",
    "image_hash_match_fraud_db": "Delivery",
    "return_pattern_abuse": "ActionsOnObjectives",
    "chargeback_history": "ActionsOnObjectives",
    "coupon_stacking_attempt": "ActionsOnObjectives",
    "price_manipulation_attempt": "Exploitation",
    "product_category_mismatch": "Delivery",
    "geographic_anomaly": "Reconnaissance",
    "gnn_ring_risk_high": "ActionsOnObjectives",
    "session_hijack_indicators": "Exploitation",
    "session_fixation": "Exploitation",
    # Insider / Privilege
    "insider_threat_signal": "ActionsOnObjectives",
    "privilege_escalation_attempt": "Exploitation",
    "lateral_movement_indicator": "Installation",
    # Network
    "active_scanning": "Reconnaissance",
    "ip_velocity_spike": "Reconnaissance",
    "port_scan": "Reconnaissance",
    "ip_risk": "Reconnaissance",
    "asn_known_proxy_tor": "Reconnaissance",
    "geoip_high_risk_country": "Reconnaissance",
    "credential_stuffing": "Exploitation",
    "brute_force": "Exploitation",
    "account_takeover": "ActionsOnObjectives",
    "phishing": "Delivery",
    "spear_phishing_link": "Delivery",
    "api_data_scraping": "ActionsOnObjectives",
    # Evasion
    "encoded_payload": "Weaponization",
    "steganography": "Weaponization",
    "log_tampering": "ActionsOnObjectives",
    "timestomping": "ActionsOnObjectives",
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


def _evidence_item(
    signal: str,
    component: str,
    contribution: float,
    *,
    cv: bool = False,
    signal_quality: str | None = None,
) -> Dict[str, Any]:
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
        "signal_quality": signal_quality or ("structural_parse" if cv else "keyword_match"),
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
    evidence.append({"signal": f"severity:{sev}", "component": "damage", "contribution": damage_base, "mitre": "", "owasp": "", "kill_chain": "", "source": "severity", "signal_quality": "heuristic"})
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
    evidence.append({"signal": f"signal_count:{total_fired}", "component": "reproducibility", "contribution": repro_base, "mitre": "", "owasp": "", "kill_chain": "", "source": "heuristic", "signal_quality": "heuristic"})
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
        evidence.append({"signal": f"actor_role:{role}", "component": "affected_users", "contribution": 8.0, "mitre": "T1078", "owasp": "", "kill_chain": "", "source": "context", "signal_quality": "structural_parse"})
    elif role in ("merchant",):
        affected_base = 6.0
        evidence.append({"signal": f"actor_role:{role}", "component": "affected_users", "contribution": 6.0, "mitre": "", "owasp": "", "kill_chain": "", "source": "context", "signal_quality": "structural_parse"})
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


def score_vuln_report(report: Any) -> Dict[str, Any]:
    """Map vulnerability findings into the DREAD model used elsewhere."""
    findings: List[Any]
    try:
        findings = list(getattr(report, "findings", None) or report.get("findings") or [])
    except Exception:
        findings = []
    try:
        risk_score = float(getattr(report, "risk_score", None) or report.get("risk_score") or 0.0)
    except Exception:
        risk_score = 0.0

    critical = 0
    high = 0
    kev_hits = 0
    semgrep_hits = 0
    exposure_hits = 0
    for item in findings:
        try:
            severity = str(getattr(item, "severity", None) or item.get("severity") or "").lower()
        except Exception:
            severity = ""
        if severity == "critical":
            critical += 1
        elif severity == "high":
            high += 1
        try:
            source = str(getattr(item, "source", None) or item.get("source") or "").lower()
            if source == "semgrep":
                semgrep_hits += 1
        except Exception:
            pass
        try:
            title = str(getattr(item, "title", None) or item.get("title") or "").lower()
            if "exposure" in title or "directory listing" in title:
                exposure_hits += 1
        except Exception:
            pass
        try:
            plain = str(getattr(item, "plain_english", None) or item.get("plain_english") or "")
            if "known exploited vulnerabilities" in plain.lower():
                kev_hits += 1
        except Exception:
            pass

    severity = "critical" if critical else ("high" if high else ("warn" if findings else "info"))
    dread = compute_dread(
        signals={
            "supply_chain": bool(findings),
            "unexpected_code_exec": semgrep_hits > 0,
            "scanner_burst": len(findings) >= 10,
            "cascading_failure": risk_score >= 7.5 or critical >= 3,
            "data_exfiltration": exposure_hits > 0,
        },
        severity=severity,
        actor_context={
            "actor_role": "merchant",
            "affected_user_fraction": min(1.0, 0.2 * high + 0.35 * critical),
            "known_exploited": kev_hits > 0,
            "internet_exposed": True,
        },
    )
    dread["vulnerability_summary"] = {
        "risk_score": round(risk_score, 2),
        "finding_count": len(findings),
        "critical_count": critical,
        "high_count": high,
        "kev_count": kev_hits,
    }
    return dread
