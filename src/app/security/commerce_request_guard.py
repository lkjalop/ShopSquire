from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


_XSS_PATTERNS = (
    re.compile(r"(?i)<\s*script\b"),
    re.compile(r"(?i)javascript\s*:"),
    re.compile(r"(?i)onerror\s*="),
    re.compile(r"(?i)onload\s*="),
    re.compile(r"(?i)<\s*img\b"),
)

_SQLI_PATTERNS = (
    re.compile(r"(?i)\bunion\s+select\b"),
    re.compile(r"(?i)\bselect\s+\*\s+from\b"),
    re.compile(r"(?i)\bdrop\s+table\b"),
    re.compile(r"(?i)\bor\s+1\s*=\s*1\b"),
    re.compile(r"(?i)['\"`;]\s*--"),
)

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"(?i)\bignore\s+(all|previous|prior)\b"),
    re.compile(r"(?i)\boverride\s+system\b"),
    re.compile(r"(?i)\bdeveloper\s+mode\b"),
    re.compile(r"(?i)\bjailbreak\b"),
)

_SKU_PAT = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$", re.IGNORECASE)
_UID_PAT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{1,127}$")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_as_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(f"{k}:{_as_text(v)}" for k, v in value.items())
    return str(value)


def inspect_commerce_request(
    *,
    surface: str,
    texts: Iterable[Any] | None = None,
    sku_values: Iterable[Any] | None = None,
    uid: str | None = None,
    quantity_values: Iterable[Any] | None = None,
) -> Dict[str, Any]:
    reasons: List[str] = []
    mitigations: List[str] = []
    mitre_attack: List[str] = []
    verdict = "allow"
    severity = "info"
    risk = 0.02

    joined_text = " ".join(_as_text(t) for t in (texts or [])).strip()
    lowered = joined_text.lower()

    if any(p.search(lowered) for p in _PROMPT_INJECTION_PATTERNS):
        reasons.append("prompt_injection_pattern")
        mitigations.extend(["request_sanitized", "log_security_event"])
        mitre_attack.append("AML.T0043")
        verdict = "block"
        severity = "high"
        risk = max(risk, 0.92)

    if any(p.search(lowered) for p in _XSS_PATTERNS):
        reasons.append("xss_pattern")
        mitigations.extend(["escape_html", "sanitize_input"])
        mitre_attack.append("T1059.007")
        verdict = "block"
        severity = "high"
        risk = max(risk, 0.95)

    if any(p.search(lowered) for p in _SQLI_PATTERNS):
        reasons.append("sqli_pattern")
        mitigations.extend(["parameterized_queries", "reject_payload"])
        mitre_attack.append("T1190")
        verdict = "block"
        severity = "high"
        risk = max(risk, 0.94)

    clean_uid = str(uid or "").strip()
    if clean_uid and not _UID_PAT.match(clean_uid):
        reasons.append("invalid_uid_format")
        mitigations.append("normalize_identifier")
        mitre_attack.append("T1190")
        verdict = "block"
        severity = "medium"
        risk = max(risk, 0.72)

    for sku in (sku_values or []):
        sku_text = str(sku or "").strip()
        if sku_text and not _SKU_PAT.match(sku_text):
            reasons.append("invalid_sku_format")
            mitigations.append("allowlist_sku_pattern")
            mitre_attack.append("T1190")
            verdict = "block"
            severity = "medium"
            risk = max(risk, 0.78)
            break

    for qty in (quantity_values or []):
        try:
            qty_int = int(qty)
        except Exception:
            reasons.append("invalid_quantity_type")
            mitigations.append("schema_validation")
            verdict = "block"
            severity = "medium"
            risk = max(risk, 0.68)
            break
        if qty_int <= 0:
            reasons.append("non_positive_quantity")
            mitigations.append("quantity_floor_1")
            verdict = "block"
            severity = "medium"
            risk = max(risk, 0.66)
            break
        if qty_int > 25:
            reasons.append("quantity_abuse_threshold")
            mitigations.append("require_manual_review")
            if verdict != "block":
                verdict = "escalate"
            severity = "medium"
            risk = max(risk, 0.64)
            break

    if verdict == "allow" and joined_text and any(token in lowered for token in ("../", "..\\", "<iframe", "%3cscript")):
        reasons.append("suspicious_encoded_payload")
        mitigations.append("request_review")
        verdict = "escalate"
        severity = "medium"
        risk = max(risk, 0.58)

    if verdict == "allow":
        mitigations.append("fast_path_allow")

    return {
        "surface": surface,
        "verdict": verdict,
        "severity": severity,
        "risk": round(float(risk), 2),
        "reasons": sorted(set(reasons)),
        "mitigations": sorted(set(mitigations)),
        "mitre_atlas": [],
        "mitre_attack": sorted(set(mitre_attack)),
    }
