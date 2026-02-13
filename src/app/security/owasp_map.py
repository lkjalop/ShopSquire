from __future__ import annotations

from typing import Dict, Any, List


OWASP_LLM_MAP = {
    "prompt_injection": "LLM01:PromptInjection",
    "jailbreak": "LLM01:PromptInjection",
    "pii": "LLM06:SensitiveInformationDisclosure",
    "pci": "LLM06:SensitiveInformationDisclosure",
    "api_key": "LLM06:SensitiveInformationDisclosure",
    "agentic_tool_abuse": "LLM08:ExcessiveAgency",
    "data_exfiltration": "LLM06:SensitiveInformationDisclosure",
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
