from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from src.app.config import load_feature_flags, get_settings


def _ff() -> Dict[str, Any]:
    try:
        return load_feature_flags(get_settings().feature_flags_path) or {}
    except Exception:
        return {}


def _thr() -> Dict[str, Any]:
    return _ff().get("SECURITY_THRESHOLDS", {})


def _hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def redact_email(addr: str | None) -> str | None:
    if not addr:
        return None
    try:
        parts = addr.split("@")
        if len(parts) != 2:
            return _hash(addr)
        return f"{_hash(parts[0])}@{_hash(parts[1])}"
    except Exception:
        return _hash(addr)


def verdict(email: Dict[str, Any], extracted: Dict[str, Any], dmarc_fail: bool = False) -> Dict[str, Any]:
    """Apply deterministic multi-signal gating and produce a verdict.

    Returns: { indicators[], iocs[], severity, reasons[], evidence_snapshot, tags[] }
    """
    thr = _thr()
    warn_n = int(thr.get("BEC_WARN_INDICATORS", 2))
    err_n = int(thr.get("BEC_ERROR_INDICATORS", 3))
    ioc_warn = int(thr.get("IOC_WARN_COUNT", 1))
    ioc_err = int(thr.get("IOC_ERROR_COUNT", 2))

    indicators: List[Dict[str, Any]] = list(extracted.get("indicators") or [])
    iocs: List[Dict[str, Any]] = list(extracted.get("iocs") or [])

    # Count denylisted IoCs
    deny_iocs = [x for x in iocs if x.get("denylisted")]
    allow_iocs = [x for x in iocs if x.get("allowlisted")]
    ind_types = set([str((i or {}).get("type") or "") for i in indicators])

    reasons: List[str] = []
    tags: List[str] = ["email_security"]
    # Add tags based on extracted indicators
    try:
        for ind in indicators:
            t = (ind or {}).get("type")
            if t == "reply_to_mismatch":
                tags.extend(["reply_to_mismatch", "brand_impersonation", "bec"])
            elif t == "lookalike_domain":
                tags.extend(["lookalike_domain", "brand_impersonation", "bec"])
            elif t == "suspicious_attachment":
                tags.append("attachment:suspicious_ext")
            elif t == "keyword":
                # Treat high-risk phrasing as BEC-ish, but do not auto-escalate alone.
                tags.append("bec")
            elif t == "anomaly":
                tags.append("anomaly")
    except Exception:
        pass
    # IoC tags
    try:
        for x in iocs:
            tt = (x or {}).get("type")
            if tt in ("url", "domain", "ip"):
                tags.append(f"ioc:{tt}")
    except Exception:
        pass
    if dmarc_fail:
        tags.append("dmarc")

    # Stable dedupe
    try:
        seen = set()
        tags = [t for t in tags if t and (t not in seen and not seen.add(t))]
    except Exception:
        pass
    # MITRE context tags (downstream-friendly)
    if any(t in ("bec", "brand_impersonation", "reply_to_mismatch", "lookalike_domain") for t in tags):
        tags.append("mitre:T1566.002")  # spearphishing via service/email
    if "lolbin_command" in ind_types or "lolbin_delivery_combo" in ind_types:
        tags.append("mitre:T1218")
    if "ransomware_extortion_pattern" in ind_types:
        tags.append("mitre:T1486")  # Data Encrypted for Impact
    if "data_exfil_intent" in ind_types:
        tags.append("mitre:T1041")  # Exfiltration Over C2 Channel
    if "c2_beacon_pattern" in ind_types:
        tags.append("mitre:T1071")  # Application Layer Protocol
    if "fileless_execution_pattern" in ind_types:
        tags.append("mitre:T1059")  # Command and Scripting Interpreter
    if "keylogger_pattern" in ind_types:
        tags.append("mitre:T1056.001")  # Keylogging

    severity = "info"
    verdict_action = "allow"
    route = "auto_resolve"
    escalation = "none"
    # Keep fuzzy clustering signals in telemetry, but exclude them from risk scoring.
    scoring_indicators = [i for i in indicators if str((i or {}).get("type") or "") != "simhash_fingerprint"]
    total_signals = len(scoring_indicators)
    if total_signals >= warn_n:
        severity = "warning"
        reasons.append("multi-signal threshold met")

    if total_signals >= err_n and (len(deny_iocs) >= ioc_err or dmarc_fail):
        severity = "error"
        reasons.append("high-signal with IoC/DMARC")

    if len(deny_iocs) >= ioc_warn and severity == "info":
        severity = "warning"
        reasons.append("denylisted IoC found")

    # Deterministic rule-first routing/actions.
    # 1) Hard security routes for policy/auth failures and malicious IoCs.
    if dmarc_fail:
        reasons.append("dmarc_fail")
    hard_security = bool(
        dmarc_fail
        or "auth_enforcement" in ind_types
        or "prompt_injection" in ind_types
        or "dangerous_tool_intent" in ind_types
        or "lolbin_delivery_combo" in ind_types
        or "confusable_homoglyph_domain" in ind_types
        or "vendor_homoglyph_impersonation" in ind_types
        or "ransomware_extortion_pattern" in ind_types
        or "data_exfil_intent" in ind_types
        or "keylogger_pattern" in ind_types
        or "c2_beacon_pattern" in ind_types
        or "fileless_execution_pattern" in ind_types
        or "malware_delivery_combo" in ind_types
        or "url_detonation_high_risk" in ind_types
        or "attachment_static_triage_high_risk" in ind_types
        or "canary_token_triggered" in ind_types
        or len(deny_iocs) >= max(ioc_err, 1)
    )
    # 2) Supplier/BEC mandatory OOB verification.
    oob_required = bool(
        "oob_verification_required" in ind_types
        or "bank_fingerprint_mismatch" in ind_types
        or ("bank_change_request" in ind_types and ("urgency_language" in ind_types or "invoice_redirect" in ind_types))
    )
    bank_change_detected = bool("bank_change_request" in ind_types or "bank_fingerprint_mismatch" in ind_types)
    oob_verified = bool(email.get("oob_verified")) or ("oob_verification_completed" in ind_types)
    if oob_required:
        reasons.append("oob_verification_required")
    if bank_change_detected and not oob_verified:
        reasons.append("mandatory_oob_verification_pending")

    if hard_security:
        verdict_action = "security_review"
        route = "security_review"
        escalation = "security_middleware"
        severity = "error"
    elif bank_change_detected and not oob_verified:
        # Hard enforcement: no bypass path for bank-change without out-of-band verification.
        verdict_action = "security_review"
        route = "security_review"
        escalation = "security_middleware"
        severity = "error"
    elif oob_required or severity == "warning":
        verdict_action = "quarantine"
        route = "human_review"
        escalation = "human_review"
    else:
        verdict_action = "allow"
        route = "auto_resolve"
        escalation = "none"

    msg_id = email.get("message_id")
    from_domain = extracted.get("meta", {}).get("from_domain")
    reply_domain = extracted.get("meta", {}).get("reply_to_domain")
    evidence = {
        "message_id_hash": _hash(str(msg_id) if msg_id else None),
        "from": redact_email(email.get("from_addr")),
        "reply_to": redact_email(email.get("reply_to")),
        "subject_hash": _hash(str(email.get("subject") or "")),
        # Avoid emitting raw domains by default; keep hashed versions for correlation.
        "from_domain_hash": _hash(str(from_domain) if from_domain else None),
        "reply_to_domain_hash": _hash(str(reply_domain) if reply_domain else None),
        "indicator_count": total_signals,
        "ioc_counts": {
            "total": len(iocs),
            "denylisted": len(deny_iocs),
            "allowlisted": len(allow_iocs),
        },
        "bank_change_detected": bank_change_detected,
        "oob_verified": oob_verified,
        "oob_verification_required": oob_required,
        "hard_security_triggered": hard_security,
    }

    return {
        "indicators": indicators,
        "iocs": iocs,
        "severity": severity,
        "verdict_action": verdict_action,
        "route": route,
        "escalation": escalation,
        "reasons": reasons,
        "evidence_snapshot": evidence,
        "tags": tags,
    }
