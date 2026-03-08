from __future__ import annotations

import base64
import math
import re
from typing import Any, Dict, List


_SHADOW_COPY_PATTERNS = [
    re.compile(r"(?i)\bvssadmin(?:\.exe)?\s+delete\s+shadows\b"),
    re.compile(r"(?i)\bwmic(?:\.exe)?\s+shadowcopy\s+delete\b"),
    re.compile(r"(?i)\bpowershell(?:\.exe)?\b.{0,120}\b(?:DeleteShadowCopy|Win32_ShadowCopy)\b"),
]

_OFFICE_SCRIPT_PATTERNS = [
    re.compile(r"(?i)\b(?:winword|excel|powerpnt|outlook)(?:\.exe)?\b.{0,120}\b(?:cmd|powershell|wscript|cscript|mshta|rundll32)(?:\.exe)?\b"),
    re.compile(r"(?i)\b(?:AutoOpen|Document_Open|Workbook_Open)\b.{0,200}\bShell\s*\("),
]

_CANARY_TARGET_PATTERNS = [
    re.compile(r"(?i)\b(?:canary|honeypot|honeytoken|decoy|bait)\b.{0,40}\b(?:encrypt|locked|rename|delete|wipe|ransom)\b"),
    re.compile(r"(?i)\b(?:encrypt|locked|rename|delete|wipe|ransom)\b.{0,40}\b(?:canary|honeypot|honeytoken|decoy|bait)\b"),
    re.compile(r"(?i)\b(?:_?canary(?:\.[a-z0-9]{1,5})?|honeytoken(?:\.[a-z0-9]{1,5})?)\b"),
]


def coverage_limits() -> Dict[str, Any]:
    return {
        "positioning": "ShopSquire is the pre-execution gate; EDR is the post-execution backstop.",
        "scope": "gateway_artifact_analysis_only",
        "in_scope": [
            "email/attachment text and metadata heuristics",
            "deterministic command-string and pattern matching",
            "pre-execution risk routing",
        ],
        "out_of_scope": [
            "runtime process telemetry",
            "kernel/memory scanning",
            "host-wide behavioral correlation",
        ],
    }


def _shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    total = float(len(data))
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    ent = 0.0
    for c in freq:
        if c == 0:
            continue
        p = c / total
        ent -= p * math.log2(p)
    return float(ent)


def _attachment_entropy_signals(attachments: List[Dict[str, Any]]) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    for a in attachments or []:
        name = str((a or {}).get("name") or "")
        raw = b""
        b64 = (a or {}).get("content_b64")
        if isinstance(b64, str) and b64.strip():
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                raw = b""
        if not raw:
            txt = str((a or {}).get("extracted_text") or "")
            raw = txt.encode("utf-8", errors="ignore")
        if len(raw) < 256:
            continue
        ent = _shannon_entropy(raw[:131072])
        if ent >= 7.2:
            findings.append({"name": name[:180], "entropy": round(ent, 4), "size_bytes": int(len(raw))})
    return {
        "triggered": bool(findings),
        "indicator_type": "ransomware_attachment_entropy_hint",
        "reason": "High-entropy attachment content may indicate encrypted/staged payload artifacts",
        "findings": findings[:10],
    }


def _text_corpus(email: Dict[str, Any]) -> str:
    parts = [str(email.get("subject") or ""), str(email.get("body") or "")]
    for a in (email.get("attachments") or []):
        if isinstance(a, dict):
            parts.append(str(a.get("name") or ""))
            parts.append(str(a.get("extracted_text") or ""))
    return "\n".join(parts).lower()


def _regex_signal(corpus: str, patterns: List[re.Pattern[str]], indicator_type: str, reason: str, max_matches: int = 8) -> Dict[str, Any]:
    matches: List[str] = []
    for p in patterns:
        for m in p.finditer(corpus):
            snippet = m.group(0).strip()
            if snippet and snippet not in matches:
                matches.append(snippet[:180])
            if len(matches) >= max_matches:
                break
        if len(matches) >= max_matches:
            break
    return {
        "triggered": bool(matches),
        "indicator_type": indicator_type,
        "reason": reason,
        "matches": matches,
    }


def analyze_ransomware_artifacts(email: Dict[str, Any]) -> Dict[str, Any]:
    attachments = [a for a in (email.get("attachments") or []) if isinstance(a, dict)]
    corpus = _text_corpus(email)

    entropy_sig = _attachment_entropy_signals(attachments)
    shadow_sig = _regex_signal(
        corpus,
        _SHADOW_COPY_PATTERNS,
        "ransomware_shadow_copy_deletion_command",
        "Shadow-copy deletion command strings detected in message artifacts",
    )
    canary_sig = _regex_signal(
        corpus,
        _CANARY_TARGET_PATTERNS,
        "ransomware_canary_targeting_pattern",
        "Canary/honeypot filename targeting patterns detected",
    )
    office_chain_sig = _regex_signal(
        corpus,
        _OFFICE_SCRIPT_PATTERNS,
        "ransomware_office_to_script_chain_indicator",
        "Office-to-script execution chain indicators found in text/macro artifacts",
    )

    sigs = [entropy_sig, shadow_sig, canary_sig, office_chain_sig]
    indicators: List[Dict[str, Any]] = []
    for s in sigs:
        if not bool(s.get("triggered")):
            continue
        indicators.append(
            {
                "type": str(s.get("indicator_type") or ""),
                "value": True,
                "reason": str(s.get("reason") or ""),
            }
        )
    return {
        "mode": "artifact_only_pre_execution",
        "signal_count": len(indicators),
        "signals": {
            "entropy_hint": entropy_sig,
            "shadow_copy_command": shadow_sig,
            "canary_targeting": canary_sig,
            "office_script_chain": office_chain_sig,
        },
        "indicators": indicators,
        "coverage_limits": coverage_limits(),
    }
