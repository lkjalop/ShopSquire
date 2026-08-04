from __future__ import annotations

from typing import Dict, Any, List

TAXONOMY_EDITIONS = {
    "owasp_llm": "OWASP Top 10 for LLM Applications 2025 v2.0",
    "owasp_api": "OWASP API Security Top 10 2023",
    "mitre_atlas": "MITRE ATLAS live catalog; mappings reviewed 2026-08-01",
    "mitre_attack": "MITRE ATT&CK Enterprise live catalog; mappings reviewed 2026-08-01",
}
MAPPING_RULE_VERSION = "shopsquire.security-map.2026-08-01.1"

OWASP_LLM_MAP = {
    "prompt_injection": "LLM01:PromptInjection",
    "jailbreak": "LLM01:PromptInjection",
    "qr_prompt_injection": "LLM01:PromptInjection",
    "ocr_prompt_injection": "LLM01:PromptInjection",
    # CV lane: treat QR indirection and injected overlay text as prompt-injection attempts.
    "qr_url_present": "LLM01:PromptInjection",
    "qr_url_suspicious": "LLM01:PromptInjection",
    "qr_external_url_detected": "LLM01:PromptInjection",
    "qr_external_url": "LLM01:PromptInjection",
    "qr_label_destination_mismatch": "LLM01:PromptInjection",
    "payment_social_engineering": "LLM01:PromptInjection",
    "cross_image_split_injection": "LLM01:PromptInjection",
    "agentic_tool_injection": "LLM01:PromptInjection",
    "prompt_injection_text": "LLM01:PromptInjection",
    "cross_modal_mismatch": "LLM05:ImproperOutputHandling",
    "manipulation_detected": "LLM05:ImproperOutputHandling",
    "adversarial_detected": "LLM05:ImproperOutputHandling",
    "ocr_yolo_label_conflict": "LLM05:ImproperOutputHandling",
    "vision_yolo_conflict": "LLM05:ImproperOutputHandling",
    "product_identity_low_confidence": "LLM09:Misinformation",
    "multimodal_attack_surface_high": "LLM01:PromptInjection",
    "pii": "LLM02:SensitiveInformationDisclosure",
    "pci": "LLM02:SensitiveInformationDisclosure",
    "pci_card_exposed": "LLM02:SensitiveInformationDisclosure",
    "api_key": "LLM02:SensitiveInformationDisclosure",
    "agentic_tool_abuse": "LLM06:ExcessiveAgency",
    "data_exfiltration": "LLM02:SensitiveInformationDisclosure",
    # Broader mappings used by observer/correlation.
    "supply_chain": "LLM03:SupplyChain",
    "training_poisoning": "LLM04:DataAndModelPoisoning",
    "poisoning_attempt": "LLM04:DataAndModelPoisoning",
    # OWASP LLM Top 10 2025 — additional mappings
    "insecure_output": "LLM05:ImproperOutputHandling",
    "model_denial_of_service": "LLM10:UnboundedConsumption",
    "improper_output_handling": "LLM05:ImproperOutputHandling",
    "overreliance": "LLM09:Misinformation",
    "model_theft": "LLM10:UnboundedConsumption",
    "model_extraction": "LLM10:UnboundedConsumption",
    "systematic_query_pattern": "LLM10:UnboundedConsumption",
    "unbounded_consumption": "LLM10:UnboundedConsumption",
    "system_prompt_leak": "LLM07:SystemPromptLeakage",
    "vector_db_poisoning": "LLM08:VectorAndEmbeddingWeaknesses",
}


# API mappings are design-control hypotheses until an observed event carries
# the referenced evidence. They never authorize or block a workflow by label.
OWASP_API_MAP = {
    "foreign_return_claim_reference": "API1:2023 Broken Object Level Authorization",
    "foreign_order_reference": "API1:2023 Broken Object Level Authorization",
    "unauthorized_return_transition": "API5:2023 Broken Function Level Authorization",
    "return_claim_automation_abuse": "API6:2023 Unrestricted Access to Sensitive Business Flows",
    "return_evidence_external_reference": "API7:2023 Server Side Request Forgery",
    "unversioned_return_endpoint": "API9:2023 Improper Inventory Management",
    "untrusted_order_or_carrier_api": "API10:2023 Unsafe Consumption of APIs",
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
    "steg_suspicious": "AML.T0043",
    "manipulation_detected": "AML.T0043",
    "adversarial_detected": "AML.T0043",
    "payment_social_engineering": "AML.T0051",
    "cross_image_split_injection": "AML.T0051",
    "agentic_tool_injection": "AML.T0051",
    "crypto_payment_uri": "AML.T0051",
    "ransomware_indicator": "AML.T0051",
    "encoded_payload_detected": "AML.T0051",
    "homoglyph_injection": "AML.T0051",
    "exif_text_injection": "AML.T0051",
    "cross_modal_mismatch": "AML.T0043",
    "ocr_yolo_label_conflict": "AML.T0015",
    "vision_yolo_conflict": "AML.T0015",
    "product_identity_low_confidence": "AML.T0043",
    "multimodal_attack_surface_high": "AML.T0051",
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


def map_signals_to_owasp_api(signals: Dict[str, bool]) -> List[str]:
    return sorted({tag for key, tag in OWASP_API_MAP.items() if signals.get(key)})


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
    owasp_api_tags = map_signals_to_owasp_api(signals)
    atlas_tags = map_signals_to_atlas(signals)
    attack_tags = map_signals_to_attack(signals)
    return {
        "severity": analysis.get("severity"),
        "risk_adj": analysis.get("risk_adj"),
        "owasp_llm": owasp_tags,
        "owasp_api": owasp_api_tags,
        "mitre_atlas": atlas_tags,
        "mitre_attack": attack_tags,
        "signals": signals,
        "taxonomy_editions": dict(TAXONOMY_EDITIONS),
        "mapping_rule_version": MAPPING_RULE_VERSION,
        "claim_status": "observed" if signals else "disproved",
        "review_status": "machine_mapped_requires_human_review",
    }
