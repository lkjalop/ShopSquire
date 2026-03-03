from __future__ import annotations

from typing import Dict, Any, List


OWASP_LLM_MAP = {
    "prompt_injection": "LLM01:PromptInjection",
    "jailbreak": "LLM01:PromptInjection",
    # CV lane: treat QR indirection and injected overlay text as prompt-injection attempts.
    "qr_url_present": "LLM01:PromptInjection",
    "qr_url_suspicious": "LLM01:PromptInjection",
    "prompt_injection_text": "LLM01:PromptInjection",
    "pii": "LLM06:SensitiveInformationDisclosure",
    "pci": "LLM06:SensitiveInformationDisclosure",
    "api_key": "LLM06:SensitiveInformationDisclosure",
    "agentic_tool_abuse": "LLM08:ExcessiveAgency",
    "data_exfiltration": "LLM06:SensitiveInformationDisclosure",
    # Broader mappings used by observer/correlation.
    "supply_chain": "LLM05:SupplyChainVulnerabilities",
    "training_poisoning": "LLM03:TrainingDataPoisoning",
    "poisoning_attempt": "LLM03:TrainingDataPoisoning",
    # OWASP LLM Top 10 2025 — additional mappings
    "insecure_output": "LLM02:InsecureOutputHandling",
    "model_denial_of_service": "LLM04:ModelDenialOfService",
    "improper_output_handling": "LLM02:InsecureOutputHandling",
    "overreliance": "LLM09:Overreliance",
    "model_theft": "LLM10:ModelTheft",
    "model_extraction": "LLM10:ModelTheft",
    "systematic_query_pattern": "LLM10:ModelTheft",
    "unbounded_consumption": "LLM04:ModelDenialOfService",
    "system_prompt_leak": "LLM07:SystemPromptLeakage",
    "vector_db_poisoning": "LLM03:TrainingDataPoisoning",
}


# MITRE ATLAS (Adversarial ML) technique mapping
MITRE_ATLAS_MAP = {
    "prompt_injection": "AML.T0051",          # LLM Prompt Injection
    "jailbreak": "AML.T0051.000",             # LLM Jailbreak (sub-technique)
    "prompt_injection_text": "AML.T0051",
    "model_theft": "AML.T0044",               # Full Model Theft
    "model_extraction": "AML.T0044.000",      # Model Extraction via API
    "systematic_query_pattern": "AML.T0044",
    "training_poisoning": "AML.T0020",         # Poison Training Data
    "poisoning_attempt": "AML.T0020",
    "adversarial_image": "AML.T0043",          # Adversarial Example (Inference)
    "gan_image_detected": "AML.T0043",
    "steg_payload_detected": "AML.T0043",
    "manipulation_detected": "AML.T0043",
    "supply_chain": "AML.T0010",               # ML Supply Chain Compromise
    "vector_db_poisoning": "AML.T0019",         # Publish Poisoned Datasets
    "data_exfiltration": "AML.T0025",           # Exfiltration via ML Inference API
    "agentic_tool_abuse": "AML.T0040",          # ML Model Backdoor Trigger
    "embedding_inversion": "AML.T0024",         # Infer Training Data Membership
}


# MITRE ATT&CK Enterprise technique mapping
MITRE_ATTACK_MAP = {
    "prompt_injection": "T1059.007",           # Command: JavaScript/Script (proxy)
    "jailbreak": "T1548",                       # Abuse Elevation Control
    "data_exfiltration": "T1041",              # Exfiltration Over C2 Channel
    "pii": "T1005",                            # Data from Local System
    "pci": "T1005",
    "api_key": "T1552.004",                    # Unsecured Credentials: Private Keys
    "supply_chain": "T1195.002",               # Supply Chain: Software Supply Chain
    "agentic_tool_abuse": "T1059",             # Command and Scripting Interpreter
    "model_theft": "T1530",                    # Data from Cloud Storage Object
    "phishing_email": "T1566.001",             # Phishing: Spearphishing Attachment
    "bec": "T1566.002",                        # Phishing: Spearphishing Link
    "scanner_burst": "T1595.002",              # Active Scanning: Vulnerability Scanning
    "brute_force": "T1110",                    # Brute Force
    "session_hijack_indicators": "T1563",      # Remote Service Session Hijacking
    "device_fingerprint_mismatch": "T1036",    # Masquerading
}


def map_signals_to_owasp(signals: Dict[str, bool]) -> List[str]:
    tags: List[str] = []
    for key, tag in OWASP_LLM_MAP.items():
        if signals.get(key):
            tags.append(tag)
    return sorted(set(tags))


def map_signals_to_atlas(signals: Dict[str, bool]) -> List[str]:
    """Map security signals to MITRE ATLAS technique IDs."""
    tags: List[str] = []
    for key, technique in MITRE_ATLAS_MAP.items():
        if signals.get(key):
            tags.append(technique)
    return sorted(set(tags))


def map_signals_to_attack(signals: Dict[str, bool]) -> List[str]:
    """Map security signals to MITRE ATT&CK Enterprise technique IDs."""
    tags: List[str] = []
    for key, technique in MITRE_ATTACK_MAP.items():
        if signals.get(key):
            tags.append(technique)
    return sorted(set(tags))


def summarize_alert(analysis: Dict[str, Any]) -> Dict[str, Any]:
    details = analysis.get("details") or {}
    signals = details.get("signals") or {}
    owasp_tags = map_signals_to_owasp(signals)
    atlas_tags = map_signals_to_atlas(signals)
    attack_tags = map_signals_to_attack(signals)
    return {
        "severity": analysis.get("severity"),
        "risk_adj": analysis.get("risk_adj"),
        "owasp_llm": owasp_tags,
        "mitre_atlas": atlas_tags,
        "mitre_attack": attack_tags,
        "signals": signals,
    }
