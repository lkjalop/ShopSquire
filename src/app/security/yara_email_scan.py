from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class YaraRuleDef:
    rule_id: str
    name: str
    pattern: str
    severity: str
    confidence: float
    indicator_type: str
    stride: List[str]
    pasta_stage_hint: str
    dread_component: str
    maestro_tactic: str
    mitre_attack: List[str]
    kev: List[str]
    cvss: float
    sbom_control: str


_RULES: List[YaraRuleDef] = [
    YaraRuleDef("YR001", "powershell_encoded_command", r"(?i)\bpowershell(?:\.exe)?\s+[-/](?:enc|encodedcommand)\b", "high", 0.95, "lolbin_command", ["Tampering", "ElevationOfPrivilege"], "Stage4:ThreatAnalysis", "exploitability", "ExecutionAbuse", ["T1059.001", "T1218"], ["CVE-2024-3094"], 8.2, "SBOM-Dependency-CVE-Correlation"),
    YaraRuleDef("YR002", "certutil_decode_loader", r"(?i)\bcertutil\b.{0,80}\b(?:-decode|-urlcache)\b", "high", 0.9, "lolbin_command", ["Tampering"], "Stage4:ThreatAnalysis", "exploitability", "PayloadDelivery", ["T1140", "T1218"], ["CVE-2024-3094"], 7.8, "SBOM-Dependency-CVE-Correlation"),
    YaraRuleDef("YR003", "shadow_copy_deletion", r"(?i)\bvssadmin\s+delete\s+shadows\b", "high", 0.98, "ransomware_extortion_pattern", ["Tampering", "DenialOfService"], "Stage5:WeaknessAndVulnerabilityAnalysis", "damage", "ImpactPrep", ["T1490", "T1486"], [], 8.6, "RuntimeGuardrail-ArtifactOnly"),
    YaraRuleDef("YR004", "wmic_process_spawn", r"(?i)\bwmic\b.{0,60}\bprocess\s+call\s+create\b", "high", 0.9, "fileless_execution_pattern", ["Tampering", "ElevationOfPrivilege"], "Stage4:ThreatAnalysis", "exploitability", "ExecutionAbuse", ["T1047", "T1059"], [], 7.7, "RuntimeGuardrail-ArtifactOnly"),
    YaraRuleDef("YR005", "mshta_remote_execution", r"(?i)\bmshta\b.{0,40}https?://", "high", 0.92, "fileless_execution_pattern", ["Tampering"], "Stage4:ThreatAnalysis", "exploitability", "ExecutionAbuse", ["T1218.005", "T1059"], [], 8.0, "RuntimeGuardrail-ArtifactOnly"),
    YaraRuleDef("YR006", "rundll32_javascript", r"(?i)\brundll32\b.{0,50}\bjavascript:", "high", 0.92, "fileless_execution_pattern", ["Tampering"], "Stage4:ThreatAnalysis", "exploitability", "ExecutionAbuse", ["T1218.011", "T1059"], [], 8.0, "RuntimeGuardrail-ArtifactOnly"),
    YaraRuleDef("YR007", "base64_pe_header", r"(?i)\bTVqQ[A-Za-z0-9+/=]{16,}\b", "medium", 0.78, "malware_delivery_combo", ["Tampering"], "Stage4:ThreatAnalysis", "discoverability", "PayloadDelivery", ["T1027", "T1140"], [], 7.1, "SBOM-Dependency-CVE-Correlation"),
    YaraRuleDef("YR008", "ransom_note_language", r"(?i)\byour\s+files\s+(?:are|were)\s+encrypted\b|\bdecrypt(?:ion)?\s+key\b", "high", 0.88, "ransomware_extortion_pattern", ["DenialOfService"], "Stage5:WeaknessAndVulnerabilityAnalysis", "damage", "Extortion", ["T1486"], [], 8.4, "RuntimeGuardrail-ArtifactOnly"),
    YaraRuleDef("YR009", "cloud_exfiltration_phrase", r"(?i)\bupload\s+(?:to|into)\s+(?:mega|dropbox|gdrive|google\s*drive|onedrive)\b", "high", 0.85, "data_exfil_intent", ["InformationDisclosure"], "Stage4:ThreatAnalysis", "affected_users", "Exfiltration", ["T1041", "T1567"], [], 7.9, "SBOM-Dependency-CVE-Correlation"),
    YaraRuleDef("YR010", "qr_payment_redirect", r"(?i)\b(?:scan\s+the\s+qr|qr\s+code)\b.{0,120}\b(?:pay|payment|beneficiary|bank)\b", "medium", 0.72, "ocr_overlay_payment_instruction", ["Spoofing", "Tampering"], "Stage3:ThreatAnalysis", "reproducibility", "SocialEngineering", ["T1566.002"], [], 6.8, "RuntimeGuardrail-ArtifactOnly"),
    YaraRuleDef("YR011", "prompt_injection_directive", r"(?i)\b(ignore\s+previous|system\s*prompt|developer\s*mode|do\s+not\s+follow\s+policy)\b", "high", 0.86, "prompt_injection", ["Tampering"], "Stage4:ThreatAnalysis", "discoverability", "LLMInstructionAbuse", ["AML.T0043", "T1566.002"], [], 7.6, "ModelInputSanitization"),
    YaraRuleDef("YR012", "dangerous_tool_intent", r"(?i)\b(execute\s+shell|dump\s+database|export\s+all\s+customers|read\s+secrets)\b", "high", 0.88, "dangerous_tool_intent", ["ElevationOfPrivilege", "InformationDisclosure"], "Stage4:ThreatAnalysis", "damage", "ToolAbuse", ["AML.T0043", "T1059"], [], 8.1, "ModelToolPolicy-Enforcement"),
    YaraRuleDef("YR013", "bec_urgent_wire", r"(?i)\b(?:urgent|asap|immediately)\b.{0,120}\b(?:wire|transfer|beneficiary|bank\s+details)\b", "medium", 0.7, "urgency_language", ["Spoofing"], "Stage3:ThreatAnalysis", "reproducibility", "BECSocialEngineering", ["T1566.002", "T1598"], [], 6.9, "VendorTrustGraph-Control"),
    YaraRuleDef("YR014", "oob_bypass_language", r"(?i)\b(?:do\s+not\s+call|no\s+verification|skip\s+approval|bypass\s+verification)\b", "high", 0.84, "oob_verification_required", ["Repudiation", "Spoofing"], "Stage4:ThreatAnalysis", "affected_users", "ApprovalBypass", ["T1566.002"], [], 7.4, "OutOfBandVerification-Control"),
    YaraRuleDef("YR015", "punycode_lookalike", r"(?i)\bxn--[a-z0-9-]{3,}\b", "medium", 0.66, "confusable_homoglyph_domain", ["Spoofing"], "Stage3:ThreatAnalysis", "discoverability", "IdentitySpoofing", ["T1586", "T1566.002"], [], 6.5, "DomainIdentity-Control"),
]

def _context(email: Dict[str, Any], extracted: Dict[str, Any] | None = None) -> str:
    extracted = extracted or {}
    subject = str(email.get("subject") or "")
    body = str(email.get("body") or "")
    attachments = email.get("attachments") or []
    attachment_text = "\n".join(
        str((a or {}).get("extracted_text") or "")[:4000]
        for a in attachments
        if str((a or {}).get("extracted_text") or "").strip()
    )[:50000]
    from_addr = str(email.get("from_addr") or "")
    reply_to = str(email.get("reply_to") or "")
    from_domain = str((extracted.get("meta") or {}).get("from_domain") or "")
    return "\n".join([subject, body, attachment_text, from_addr, reply_to, from_domain])


def scan_email_yara(email: Dict[str, Any], extracted: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Run YARA-style scanning with optional yara-python backend and deterministic fallback."""
    haystack = _context(email, extracted)
    matches: List[Dict[str, Any]] = []

    try:
        import yara  # type: ignore

        engine = "yara-python"
        yara_available = True
    except Exception:
        yara = None
        engine = "regex-fallback"
        yara_available = False

    compiled: List[Tuple[YaraRuleDef, Any]] = []
    if yara_available and yara is not None:
        for r in _RULES:
            src = f'rule {r.rule_id}_{r.name} {{ strings: $a = /{r.pattern}/ nocase condition: $a }}'
            try:
                compiled.append((r, yara.compile(source=src)))
            except Exception:
                compiled.append((r, None))
    else:
        compiled = [(r, None) for r in _RULES]

    for rule, yr in compiled:
        fired = False
        if yr is not None:
            try:
                fired = bool(yr.match(data=haystack))
            except Exception:
                fired = False
        if not fired:
            try:
                fired = bool(re.search(rule.pattern, haystack, flags=re.IGNORECASE | re.MULTILINE))
            except re.error:
                fired = False
        if not fired:
            continue
        matches.append(
            {
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "severity": rule.severity,
                "confidence": rule.confidence,
                "indicator_type": rule.indicator_type,
                "correlation": {
                    "stride": rule.stride,
                    "pasta_stage_hint": rule.pasta_stage_hint,
                    "dread_component": rule.dread_component,
                    "maestro_tactic": rule.maestro_tactic,
                    "mitre_attack": rule.mitre_attack,
                    "kev": rule.kev,
                    "cvss": rule.cvss,
                    "sbom_control": rule.sbom_control,
                },
            }
        )

    return {
        "engine": engine,
        "rules_loaded": len(_RULES),
        "match_count": len(matches),
        "matches": matches,
    }
