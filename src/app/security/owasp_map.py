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
}


def map_signals_to_owasp(signals: Dict[str, bool]) -> List[str]:
    tags: List[str] = []
    for key, tag in OWASP_LLM_MAP.items():
        if signals.get(key):
            tags.append(tag)
    return sorted(set(tags))


def summarize_alert(analysis: Dict[str, Any]) -> Dict[str, Any]:
    details = analysis.get("details") or {}
    signals = details.get("signals") or {}
    tags = map_signals_to_owasp(signals)
    return {
        "severity": analysis.get("severity"),
        "risk_adj": analysis.get("risk_adj"),
        "owasp_llm": tags,
        "signals": signals,
    }
