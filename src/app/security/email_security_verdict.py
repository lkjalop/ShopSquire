from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from src.app.config import load_feature_flags, get_settings
from src.app.services.ml_decision_gate import gate_decision, score_with_learned_model


def _ff() -> Dict[str, Any]:
    try:
        return load_feature_flags(get_settings().feature_flags_path) or {}
    except Exception:
        return {}


def _thr() -> Dict[str, Any]:
    return _ff().get("SECURITY_THRESHOLDS", {})


def _as_list(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x or "").strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


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


def verdict(
    email: Dict[str, Any],
    extracted: Dict[str, Any],
    dmarc_fail: bool = False,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
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
            elif t in ("vendor_homoglyph_impersonation", "confusable_homoglyph_domain"):
                tags.extend(["unicode_confusable", "brand_impersonation", "bec"])
            elif t in ("account_name_mismatch", "legal_entity_mismatch"):
                tags.extend(["vendor_entity_mismatch", "supply_chain", "bec"])
            elif t == "suspicious_attachment":
                tags.append("attachment:suspicious_ext")
            elif t in ("attachment_steganography_suspected", "attachment_steg_score_elevated"):
                tags.extend(["attachment:stego", "data_hiding"])
            elif t == "keyword":
                # Treat high-risk phrasing as BEC-ish, but do not auto-escalate alone.
                tags.append("bec")
            elif t == "anomaly":
                tags.append("anomaly")
            elif t in ("lolbin_command", "lolbin_delivery_combo"):
                tags.append("lolbin")
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
    if "account_name_mismatch" in ind_types or "legal_entity_mismatch" in ind_types:
        tags.append("mitre:T1598")  # Phishing/Supplier relationship abuse
    try:
        seen2 = set()
        tags = [t for t in tags if t and (t not in seen2 and not seen2.add(t))]
    except Exception:
        pass

    severity = "info"
    verdict_action = "allow"
    route = "auto_resolve"
    escalation = "none"
    # Keep fuzzy clustering signals in telemetry, but exclude them from risk scoring.
    scoring_indicators = [
        i for i in indicators
        if str((i or {}).get("type") or "") not in ("simhash_fingerprint", "vendor_baseline_missing", "ocr_overlay_benign_catalog")
    ]
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
    bank_change_detected = bool(
        "bank_change_request" in ind_types
        or "bank_fingerprint_mismatch" in ind_types
        or "bank_fingerprint_baseline_mismatch" in ind_types
        or "bank_fingerprint_extracted_mismatch" in ind_types
        or "account_name_mismatch" in ind_types
    )
    oob_verified = bool(email.get("oob_verified")) or ("oob_verification_completed" in ind_types)
    thread_hijack_combo = bool(
        "reply_chain_hijack" in ind_types
        and ("bank_change_request" in ind_types or "invoice_redirect" in ind_types or "urgency_language" in ind_types)
        and not oob_verified
    )
    hard_security = bool(
        dmarc_fail
        or "auth_enforcement" in ind_types
        or "prompt_injection" in ind_types
        or "dangerous_tool_intent" in ind_types
        or "lolbin_command" in ind_types
        or "lolbin_delivery_combo" in ind_types
        or "confusable_homoglyph_domain" in ind_types
        or "vendor_homoglyph_impersonation" in ind_types
        or "account_name_mismatch" in ind_types
        or "legal_entity_mismatch" in ind_types
        or "bank_fingerprint_baseline_mismatch" in ind_types
        or "bank_fingerprint_extracted_mismatch" in ind_types
        or "ocr_overlay_malicious_text" in ind_types
        or "ocr_overlay_unicode_confusable_payment" in ind_types
        or "ransomware_extortion_pattern" in ind_types
        or "data_exfil_intent" in ind_types
        or "keylogger_pattern" in ind_types
        or "c2_beacon_pattern" in ind_types
        or "fileless_execution_pattern" in ind_types
        or "malware_delivery_combo" in ind_types
        or "url_detonation_high_risk" in ind_types
        or "attachment_static_triage_high_risk" in ind_types
        or "attachment_steganography_suspected" in ind_types
        or "canary_token_triggered" in ind_types
        or thread_hijack_combo
        or len(deny_iocs) >= max(ioc_err, 1)
    )
    # 2) Supplier/BEC mandatory OOB verification.
    oob_required = bool(
        "oob_verification_required" in ind_types
        or "bank_fingerprint_mismatch" in ind_types
        or "bank_fingerprint_baseline_mismatch" in ind_types
        or "bank_fingerprint_extracted_mismatch" in ind_types
        or "account_name_mismatch" in ind_types
        or "legal_entity_mismatch" in ind_types
        or "reply_chain_hijack" in ind_types
        or "domain_age_insufficient_for_payment_instruction" in ind_types
        or "ocr_overlay_payment_instruction" in ind_types
        or ("bank_change_request" in ind_types and ("urgency_language" in ind_types or "invoice_redirect" in ind_types))
    )
    if oob_required:
        reasons.append("oob_verification_required")
    if bank_change_detected and not oob_verified:
        reasons.append("mandatory_oob_verification_pending")

    # Shared ML gate (calibrated allow/review/block) for non-hard routing.
    # Hard security and mandatory OOB controls still override fail-closed.
    gate_cfg = thr.get("ML_DECISION_GATE", {}) if isinstance(thr.get("ML_DECISION_GATE"), dict) else {}
    ml_enabled = bool(gate_cfg.get("enabled", True))
    learned_rollout_enabled = bool(gate_cfg.get("LEARNED_ML_GATE_ENABLED", True))
    learned_allowlist = _as_list(gate_cfg.get("LEARNED_ML_GATE_TENANT_ALLOWLIST"))
    learned_canary_percent = int(gate_cfg.get("LEARNED_ML_GATE_CANARY_PERCENT", 100) or 100)
    shadow_mode = bool(gate_cfg.get("SHADOW_MODE_ENABLED", False))
    ml_weights = gate_cfg.get("weights") if isinstance(gate_cfg.get("weights"), dict) else {
        "signal_density": 0.26,
        "deny_ioc_density": 0.22,
        "auth_fail": 0.18,
        "dangerous_intent": 0.18,
        "supplier_bec_unverified": 0.16,
    }
    ml_bias = float(gate_cfg.get("bias", 0.0) or 0.0)
    ml_allow_thr = float(gate_cfg.get("allow_threshold", 0.35) or 0.35)
    ml_block_thr = float(gate_cfg.get("block_threshold", 0.7) or 0.7)

    ml_features = {
        "signal_density": min(1.0, float(total_signals) / 6.0),
        "deny_ioc_density": min(1.0, float(len(deny_iocs)) / 3.0),
        "auth_fail": 1.0 if (dmarc_fail or "auth_enforcement" in ind_types) else 0.0,
        "dangerous_intent": 1.0 if (
            "prompt_injection" in ind_types
            or "dangerous_tool_intent" in ind_types
            or "lolbin_command" in ind_types
            or "lolbin_delivery_combo" in ind_types
            or "data_exfil_intent" in ind_types
            or "fileless_execution_pattern" in ind_types
            or "c2_beacon_pattern" in ind_types
        ) else 0.0,
        "supplier_bec_unverified": 1.0 if (bank_change_detected and not oob_verified) else 0.0,
    }
    score_pack = score_with_learned_model(
        domain="email_security",
        features=ml_features,
        tenant_id=tenant_id,
        fallback_weights={str(k): float(v) for k, v in ml_weights.items()},
        fallback_bias=ml_bias,
        rollout_enabled=learned_rollout_enabled,
        tenant_allowlist=learned_allowlist,
        canary_percent=learned_canary_percent,
    )
    ml_raw = float(score_pack.get("raw_score") or 0.0)
    ml_cal = score_pack.get("calibrated_score")
    ml_gate = gate_decision(
        domain="email_security",
        raw_score=ml_raw,
        allow_threshold=ml_allow_thr,
        block_threshold=ml_block_thr,
        calibration_agent="email_security",
        precalibrated_score=float(ml_cal) if ml_cal is not None else None,
        metadata={
            "feature_count": int(total_signals),
            "deny_iocs": int(len(deny_iocs)),
            "dmarc_fail": bool(dmarc_fail),
            "model_source": score_pack.get("model_source"),
            "calibration_source": score_pack.get("calibration_source"),
            "artifact_version": score_pack.get("artifact_version"),
            "feature_coverage": score_pack.get("feature_coverage"),
            "rollout_active": bool(score_pack.get("rollout_active")),
            "rollout_enabled": learned_rollout_enabled,
            "allowlist_enabled": bool(learned_allowlist),
            "canary_percent": learned_canary_percent,
        },
    ) if ml_enabled else {"domain": "email_security", "decision": "review", "raw_score": ml_raw, "calibrated_score": ml_raw, "thresholds": {"allow": ml_allow_thr, "block": ml_block_thr}, "confidence": 0.5, "uncertainty": 0.5}

    shadow_gate = None
    if shadow_mode:
        shadow_pack = score_with_learned_model(
            domain="email_security",
            features=ml_features,
            tenant_id=tenant_id,
            fallback_weights={str(k): float(v) for k, v in ml_weights.items()},
            fallback_bias=ml_bias,
            rollout_enabled=False,
            tenant_allowlist=[],
            canary_percent=0,
        )
        shadow_gate = gate_decision(
            domain="email_security",
            raw_score=float(shadow_pack.get("raw_score") or 0.0),
            allow_threshold=ml_allow_thr,
            block_threshold=ml_block_thr,
            calibration_agent="email_security",
            precalibrated_score=float(shadow_pack.get("calibrated_score") or shadow_pack.get("raw_score") or 0.0),
            metadata={
                "model_source": shadow_pack.get("model_source"),
                "calibration_source": shadow_pack.get("calibration_source"),
                "artifact_version": shadow_pack.get("artifact_version"),
                "shadow": True,
            },
        )

    if hard_security:
        if thread_hijack_combo:
            reasons.append("thread_hijack_plus_payment_change")
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
    else:
        # ML gate controls final routing outside hard fail-closed paths.
        # Keep false-positive risk low: hard controls own security_review; ML block routes to human review.
        dec = str(ml_gate.get("decision") or "review")
        if dec == "block":
            verdict_action = "quarantine"
            route = "human_review"
            escalation = "human_review"
            severity = "warning" if severity == "info" else severity
            reasons.append("ml_gate_block")
        elif dec == "review" or oob_required or severity == "warning":
            verdict_action = "quarantine"
            route = "human_review"
            escalation = "human_review"
            severity = "warning" if severity == "info" else severity
            reasons.append("ml_gate_review")
        else:
            verdict_action = "allow"
            route = "auto_resolve"
            escalation = "none"
            reasons.append("ml_gate_allow")

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
        "ml_gate": ml_gate,
        "ml_features": {k: round(float(v), 4) for k, v in ml_features.items()},
        "ml_gate_shadow": shadow_gate,
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
        "ml_gate": ml_gate,
        "ml_gate_shadow": shadow_gate,
    }
