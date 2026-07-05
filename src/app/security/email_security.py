from __future__ import annotations

from typing import Any, Dict, Tuple, List
import base64
import json
import xml.etree.ElementTree as ET
import zipfile
import io
import re
import os
import logging
from difflib import SequenceMatcher

from src.app.observability.telemetry import telemetry_emit
from src.app.config import load_feature_flags, get_settings
from src.app.services.ticketing import TicketingAgent
import hashlib
from src.app.services.decision_log import log_decision, log_trace_event

from src.app.security.email_security_rules import extract_domain, extract_indicators
from src.app.security.email_security_verdict import verdict as compute_verdict
from src.app.security.email_sender_trust import score_sender_trust, update_sender_trust
from src.app.security.threshold_tuning import get_runtime_thresholds
from src.app.services.security_playbooks import select_cv_playbook
from src.app.security.email_enrichment import enrich_iocs, detonate_targets
from src.app.security.email_attachment_intel import analyze_email_artifacts
from src.app.security.email_attachment_parser import hydrate_attachments_from_bytes
from src.app.security.email_header_forensics import analyze_email_headers
from src.app.security.mailbox_compromise import analyze_mailbox_compromise
from src.app.security.phishing_page_detector import analyze_phishing_targets
from src.app.security.yara_email_scan import scan_email_yara
from src.app.security.semantic_bec_scorer import score_semantic_bec
from src.app.security.thread_conversation_graph import analyze_thread_conversation_graph
from src.app.security.passive_payload_analysis import classify_passive_payload
from src.app.security.supplier_governance_store import (
    build_incident_graph_snapshot,
    build_vendor_trust_graph_snapshot,
    update_supplier_governance_snapshot,
)
from src.app.security.bec_kill_chain import infer_bec_kill_chain
from src.app.security.bimi_verifier import verify_bimi_provider_backed
from src.app.security.ransomware_detector import analyze_ransomware_artifacts, coverage_limits as ransomware_coverage_limits
from src.app.security.siem_adapter import build_normalized_security_event, emit_security_handoff
from src.app.security.threat_enrichment import enrich_context, infer_kill_chain_stage
from src.app.security.threat_hunter_leads import build_threat_hunter_leads
from src.app.security.maestro_boundaries import validate_agent_action
from src.app.security.email_dns_verify import run_dns_auth_checks, run_dns_auth_checks_parallel
import time
from src.app.services.intake_gate import (
    normalize_email_intake,
    sanitize_attachment_ocr_for_llm,
    strict_attachment_ingest_gate,
)
from src.app.services.playbook_engine import start_playbook_run, append_playbook_step, execute_typed_actions, complete_playbook_run
from src.app.security.control_registry import get_control_record, get_control_registry_version
from src.app.security.framework_correlation import correlate_security_analysis
from src.app.services.trust_routing import fuse_security_trust_score

_RATE_BUCKETS: dict[str, list[float]] = {}
logger = logging.getLogger("shopsquire.email_security")
_REFERENCE_NAME_TOKENS = ("guide", "summary", "matrix", "taxonomy", "playbook", "spec", "report", "runbook")
_TRAINING_NAME_TOKENS = ("testing_guide", "detection_playbook_summary", "email_threat_taxonomy")
_THREAT_SAMPLE_NAME_TOKENS = ("sample_", "homoglyph", "thread_hijacking", "ceo_fraud", "email_c2_beaconing")
_REFERENCE_TEXT_PATTERNS = (
    "detection playbook summary",
    "email threat taxonomy",
    "testing guide",
    "security training",
    "analyst workflow",
    "recommended detections",
)
_THREAT_SAMPLE_TEXT_PATTERNS = (
    "threat type:",
    "detection focus:",
    "scenario context:",
    "sample id:",
    "attack chain",
    "expected detection",
)


def _hash16(value: str | None) -> str | None:
    """Return the first 16 hex chars of SHA-256(value), or None for empty input."""
    if not value:
        return None
    import hashlib
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _record_runtime_error(
    errors: list[dict[str, Any]],
    *,
    stage: str,
    exc: Exception,
    severity: str = "warning",
    details: Dict[str, Any] | None = None,
) -> None:
    msg = str(exc)[:240]
    logger.warning("email_security.%s_failed: %s", stage, msg)
    row: dict[str, Any] = {"stage": stage, "error": msg, "severity": severity}
    if isinstance(details, dict) and details:
        row["details"] = details
    errors.append(row)
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _classify_email_content_mode(email: Dict[str, Any]) -> Dict[str, Any]:
    attachments = [dict(a or {}) for a in (email.get("attachments") or []) if isinstance(a, dict)]
    attachment_names = [str(a.get("name") or "").strip().lower() for a in attachments]
    subject = str(email.get("subject") or "").strip().lower()
    body = str(email.get("body") or "").strip().lower()
    combined = " ".join([subject, body] + attachment_names)

    reasons: List[str] = []
    mode = "real_email"
    confidence = 0.35

    reference_hits = [tok for tok in _REFERENCE_NAME_TOKENS if tok in combined]
    training_hits = [tok for tok in _TRAINING_NAME_TOKENS if tok in combined]
    sample_hits = [tok for tok in _THREAT_SAMPLE_NAME_TOKENS if tok in combined]
    reference_text_hits = [tok for tok in _REFERENCE_TEXT_PATTERNS if tok in body or tok in subject]
    sample_text_hits = [tok for tok in _THREAT_SAMPLE_TEXT_PATTERNS if tok in body or tok in subject]

    markdown_like = any(name.endswith((".md", ".txt")) for name in attachment_names)
    only_reference_extensions = bool(attachment_names) and all(
        (name.endswith((".md", ".txt", ".json")) or any(tok in name for tok in _REFERENCE_NAME_TOKENS + _THREAT_SAMPLE_NAME_TOKENS))
        for name in attachment_names
    )

    if training_hits or (reference_text_hits and only_reference_extensions):
        mode = "security_training_material"
        reasons.extend(training_hits or reference_text_hits)
        confidence = 0.96 if training_hits else 0.88
    elif sample_hits or (sample_text_hits and markdown_like):
        mode = "threat_sample"
        reasons.extend(sample_hits or sample_text_hits)
        confidence = 0.91 if sample_hits else 0.82
    elif reference_hits or (reference_text_hits and markdown_like):
        mode = "reference_content"
        reasons.extend(reference_hits or reference_text_hits)
        confidence = 0.86 if reference_hits else 0.8

    return {
        "mode": mode,
        "confidence": round(confidence, 3),
        "reasons": list(dict.fromkeys([r for r in reasons if r]))[:8],
        "only_reference_attachments": only_reference_extensions,
        "attachment_names": attachment_names[:8],
        "suppress_keyword_only_escalation": mode in {"reference_content", "security_training_material"},
    }


def _has_direct_attachment_risk(email: Dict[str, Any]) -> bool:
    for att in (email.get("attachments") or []):
        if not isinstance(att, dict):
            continue
        if att.get("linked_artifact") or att.get("ssn_detected") or att.get("pii_detected"):
            return True
        if bool(att.get("steg_suspicious")):
            return True
        if bool(att.get("bank_fields")) and str(att.get("name") or "").lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
            return True
        if bool(att.get("qr_external_url_detected")):
            return True
    return False


def _apply_reference_material_suppression(
    verdict: Dict[str, Any],
    *,
    email: Dict[str, Any],
    extracted: Dict[str, Any],
    content_classification: Dict[str, Any],
    dmarc_fail: bool,
    enrichment: Dict[str, Any] | None = None,
    detonation: Dict[str, Any] | None = None,
) -> None:
    if str(content_classification.get("mode") or "real_email") not in {"reference_content", "security_training_material"}:
        return
    indicator_types = {str((i or {}).get("type") or "") for i in (extracted.get("indicators") or [])}
    reason_types = {str(x or "") for x in (verdict.get("reasons") or [])}
    hard_indicator_types = {
        "confusable_homoglyph_domain",
        "vendor_homoglyph_impersonation",
        "lookalike_domain",
        "reply_chain_hijack",
        "thread_hijack",
        "bimi_visual_brand_mismatch",
        "dangerous_tool_intent",
        "prompt_injection",
        "lolbin_command",
        "c2_beacon_pattern",
        "data_exfil_intent",
    }
    if bool(content_classification.get("only_reference_attachments")):
        hard_indicator_types = {
            "confusable_homoglyph_domain",
            "vendor_homoglyph_impersonation",
            "lookalike_domain",
            "reply_chain_hijack",
            "thread_hijack",
            "bimi_visual_brand_mismatch",
        }
    hard_reason_types = {"yara_high_confidence_match", "forced_reauth_required"}
    if dmarc_fail or (indicator_types & hard_indicator_types) or (reason_types & hard_reason_types):
        return
    if _has_direct_attachment_risk(email):
        return
    previous = {
        "severity": verdict.get("severity"),
        "route": verdict.get("route"),
        "verdict_action": verdict.get("verdict_action"),
        "escalation": verdict.get("escalation"),
        "reasons": list(verdict.get("reasons") or []),
    }
    verdict["severity"] = "info"
    verdict["route"] = "auto_resolve"
    verdict["verdict_action"] = "allow"
    verdict["escalation"] = "none"
    verdict["reasons"] = list(
        dict.fromkeys(
            [
                x for x in (verdict.get("reasons") or [])
                if x not in {
                    "urgent_payment_language",
                    "payment_change_request",
                    "c2_beacon_pattern",
                    "oob_verification_required",
                    "mandatory_oob_verification_pending",
                    "forced_reauth_required",
                    "llm_policy_gate_denied",
                    "qr_url_not_allowlisted",
                    "ingest_gate_blocked_attachment",
                    "yara_rule_match_detected",
                    "multi-signal threshold met",
                }
            ]
            + ["reference_material_context"]
        )
    )
    verdict["tags"] = list(dict.fromkeys(list(verdict.get("tags") or []) + ["content_mode:reference_material"]))
    if isinstance(verdict.get("evidence_snapshot"), dict):
        verdict["evidence_snapshot"]["suppressed_keyword_only_escalation"] = {
            "applied": True,
            "previous": previous,
            "content_mode": content_classification.get("mode"),
        }


def _llm_control_policy(extracted: Dict[str, Any], *, ff: Dict[str, Any] | None = None) -> Dict[str, Any]:
    cfg = (ff or {}).get("SECURITY_THRESHOLDS", {}) if isinstance(ff, dict) else {}
    allow_tools = [str(x) for x in (cfg.get("EMAIL_TOOL_ALLOWLIST", ["ioc_lookup", "url_sandbox", "ticket_create"]) or [])]
    disallow_intents = [str(x) for x in (cfg.get("EMAIL_BLOCKED_TOOL_INTENTS", ["execute_shell", "export_all_data", "dump_database"]) or [])]
    ind_types = {str((i or {}).get("type") or "") for i in (extracted.get("indicators") or [])}
    blocked_intents: list[str] = []
    if "dangerous_tool_intent" in ind_types:
        blocked_intents.extend(disallow_intents)
    if "prompt_injection" in ind_types:
        blocked_intents.append("prompt_injection_attempt")
    return {
        "allow_tools": allow_tools,
        "blocked_intents": sorted(set([x for x in blocked_intents if x])),
        "sandbox_required": True,
        "policy_gate": "deny" if blocked_intents else "allow",
    }


def _llm_assist_summary(email: Dict[str, Any], extracted: Dict[str, Any], verdict: Dict[str, Any], *, ff: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Secondary AI assist only. Never authoritative for verdict/routing."""
    enabled = bool((ff or {}).get("EMAIL_LLM_ASSIST_ENABLED", False))
    subject = str(email.get("subject") or "")
    reasons = list(verdict.get("reasons") or [])
    ind_types = [str((x or {}).get("type") or "") for x in (extracted.get("indicators") or [])]
    heuristic_summary = (
        f"Rule-first verdict={verdict.get('verdict_action')} route={verdict.get('route')}. "
        f"Signals={', '.join(ind_types[:8]) or 'none'}. Subject='{subject[:120]}'."
    )
    secondary_risk = min(1.0, (len(ind_types) * 0.08) + (0.25 if verdict.get("severity") == "error" else 0.0))

    if enabled:
        try:
            import json as _json
            import os as _os
            from src.app.services.llm_providers import get_provider

            _email_llm_provider = _os.getenv("EMAIL_SECURITY_LLM_PROVIDER", "ollama")
            _email_llm_model = _os.getenv("EMAIL_SECURITY_LLM_MODEL", _os.getenv("OLLAMA_SMALL_MODEL", "qwen2.5:14b"))
            body_snippet = str(email.get("body") or "")[:600]
            prompt = (
                'You are a non-authoritative email security analyst. Respond with JSON only:\n'
                '{"summary":"<2-3 sentence finding>","missed_signals":["<signal>"],"attack_stage":"<stage>","mitre_techniques":["<T-id>"]}\n\n'
                f"Rule-engine verdict: {verdict.get('verdict_action')} / route={verdict.get('route')} / severity={verdict.get('severity')}\n"
                f"Email subject: {subject[:200]}\n"
                f"Body snippet: {body_snippet}\n"
                f"Detected signal types: {', '.join(ind_types[:12]) or 'none'}\n"
                f"Reasons: {'; '.join(reasons[:8])}\n"
                "Flag anything the rule engine may have missed. Do NOT override the verdict."
            )
            result = get_provider(_email_llm_provider).generate(
                prompt, model=_email_llm_model, max_tokens=512, temperature=0.1
            )
            llm_text = str(result.get("text") or "").strip()
            # Reject stub/error responses
            if llm_text and not llm_text.startswith("["):
                parsed: Dict[str, Any] = {}
                try:
                    import re as _re
                    m = _re.search(r'\{.*\}', llm_text, _re.DOTALL)
                    if m:
                        parsed = _json.loads(m.group(0))
                except Exception:
                    pass
                return {
                    "enabled": True,
                    "source": "llm_assist",
                    "provider": result.get("provider"),
                    "model": _email_llm_model,
                    "summary": parsed.get("summary") or llm_text[:400],
                    "missed_signals": list(parsed.get("missed_signals") or [])[:8],
                    "attack_stage": str(parsed.get("attack_stage") or ""),
                    "mitre_techniques": list(parsed.get("mitre_techniques") or [])[:10],
                    "secondary_risk_signal": round(float(secondary_risk), 3),
                    "non_authoritative": True,
                    "reasons": reasons[:8],
                }
        except Exception:
            pass  # fall through to heuristic

    return {
        "enabled": enabled,
        "source": "heuristic_assist",
        "summary": heuristic_summary,
        "secondary_risk_signal": round(float(secondary_risk), 3),
        "non_authoritative": True,
        "reasons": reasons[:6],
    }

def _within_rate_limit(key: str, per_min: int, enabled: bool) -> tuple[bool, int]:
    if not enabled:
        return True, 0
    # Prefer Redis for multi-worker consistency; fall back to in-memory if unavailable.
    try:
        from src.app.deps import get_redis

        r = get_redis()
        if r.__class__.__name__ != "DummyRedis":
            now = time.time()
            bucket = int(now // 60)
            rk = f"rl:email_security:{key}:{bucket}"
            count = int(r.incrby(rk, 1) or 0)
            try:
                if count == 1:
                    r.expire(rk, 70)
            except Exception:
                pass
            return (count <= per_min), count
    except Exception:
        pass
    now = time.time()
    window_start = now - 60.0
    bucket = _RATE_BUCKETS.get(key, [])
    bucket = [t for t in bucket if t >= window_start]
    allowed = len(bucket) < per_min
    if allowed:
        bucket.append(now)
    _RATE_BUCKETS[key] = bucket
    return allowed, len(bucket)


def _spoof_flood_load_shed_state(ff: Dict[str, Any], tenant_id: str | None, indicators: list[dict] | None) -> Dict[str, Any]:
    cfg = ff.get("SPOOF_FLOOD_LOAD_SHED", {}) if isinstance(ff, dict) else {}
    enabled = bool(cfg.get("enabled", False))
    per_min = int(cfg.get("per_min", 60))
    queue_limit = int(cfg.get("tenant_queue_limit", 120))
    fast_path_threshold = int(cfg.get("fast_path_threshold", max(1, int(per_min * 0.6))))
    budget_cap_per_day = int(cfg.get("budget_cap_per_day", 0))
    require_spoof_signals = bool(cfg.get("require_spoof_signals", True))
    indicator_types = {str((i or {}).get("type") or "") for i in (indicators or [])}
    spoof_signals = {
        "reply_to_mismatch",
        "lookalike_domain",
        "confusable_homoglyph_domain",
        "vendor_homoglyph_impersonation",
        "auth_enforcement",
        "vendor_domain_mismatch",
        "reply_chain_hijack",
    }
    has_spoof_signals = bool(indicator_types & spoof_signals)
    should_count = enabled and (has_spoof_signals or not require_spoof_signals)
    if not should_count:
        return {
            "active": False,
            "enabled": enabled,
            "reason": "not_applicable",
            "has_spoof_signals": has_spoof_signals,
            "per_min": per_min,
            "queue_limit": queue_limit,
            "fast_path_only": False,
            "budget_exceeded": False,
            "observed_per_min": 0,
        }
    tenant_key = tenant_id or "default"
    allowed, count = _within_rate_limit(f"spoof_flood:{tenant_key}", per_min=per_min, enabled=True)

    # Best-effort per-tenant queue depth and daily budget checks.
    queue_depth = int(count)
    budget_used = 0
    budget_exceeded = False
    try:
        from src.app.deps import get_redis

        r = get_redis()
        if r.__class__.__name__ != "DummyRedis":
            queue_depth = int(r.incrby(f"email_security:queue_depth:{tenant_key}", 1) or 0)
            r.expire(f"email_security:queue_depth:{tenant_key}", 120)
            if budget_cap_per_day > 0:
                day_key = time.strftime("%Y%m%d", time.gmtime())
                bkey = f"email_security:cost:{tenant_key}:{day_key}"
                budget_used = int(r.incrby(bkey, 1) or 0)
                r.expire(bkey, 172800)
                budget_exceeded = budget_used > budget_cap_per_day
    except Exception:
        budget_used = int(count)
        budget_exceeded = bool(budget_cap_per_day > 0 and budget_used > budget_cap_per_day)

    queue_exceeded = queue_limit > 0 and queue_depth > queue_limit
    fast_path_only = bool(queue_depth >= fast_path_threshold or budget_exceeded)
    active = (not bool(allowed)) or queue_exceeded or budget_exceeded
    if budget_exceeded:
        reason = "budget_cap_exceeded"
    elif queue_exceeded:
        reason = "tenant_queue_limit_exceeded"
    elif active:
        reason = "flood_threshold_exceeded"
    else:
        reason = "below_threshold"
    return {
        "active": active,
        "enabled": enabled,
        "reason": reason,
        "has_spoof_signals": has_spoof_signals,
        "per_min": per_min,
        "queue_limit": queue_limit,
        "queue_depth": queue_depth,
        "fast_path_only": fast_path_only,
        "fast_path_threshold": fast_path_threshold,
        "budget_cap_per_day": budget_cap_per_day,
        "budget_used": budget_used,
        "budget_exceeded": budget_exceeded,
        "observed_per_min": int(count),
    }

def _dedupe_ok(message_id: str | None, tenant_id: str | None) -> bool:
    """Return True if we should proceed with side-effects (tickets) for this message.

    Uses Redis when available; falls back to best-effort True in dev/test.
    """
    mid = (message_id or "").strip()
    if not mid:
        return True
    h = _hash16(mid)
    if not h:
        return True
    try:
        from src.app.deps import get_redis

        r = get_redis()
        if r.__class__.__name__ == "DummyRedis":
            return True
        k = f"dedupe:email_security:{tenant_id or 'default'}:{h}"
        if r.get(k):
            return False
        r.setex(k, 86400, "1")
        return True
    except Exception:
        return True


def _ioc_quality(iocs: list[dict], *, block_thr: float = 0.8, allow_thr: float = 0.75, margin: float = 0.1) -> dict:
    per_source: dict[str, dict[str, float]] = {}
    deny_scores: list[float] = []
    allow_scores: list[float] = []
    conflicts = 0
    by_type_counts: dict[str, int] = {}
    for i in iocs or []:
        t = str(i.get("type") or "unknown").lower()
        src = str(i.get("source") or "unknown")
        conf = float(i.get("source_confidence") or 0.5)
        if i.get("denylisted"):
            conf = min(1.0, conf + 0.15)
            deny_scores.append(conf)
        if i.get("allowlisted"):
            conf = min(1.0, conf + 0.1)
            allow_scores.append(conf)
        if bool(i.get("allowlisted")) and bool(i.get("denylisted")):
            conflicts += 1
        by_type_counts[t] = int(by_type_counts.get(t, 0)) + 1
        bucket = per_source.setdefault(src, {"sum_conf": 0.0, "count": 0.0})
        bucket["sum_conf"] += conf
        bucket["count"] += 1.0
    out_src = {}
    for k, v in per_source.items():
        c = max(1.0, float(v.get("count") or 1.0))
        out_src[k] = round(float(v.get("sum_conf") or 0.0) / c, 4)
    deny_score = round(sum(deny_scores) / max(1, len(deny_scores)), 4) if deny_scores else 0.0
    allow_score = round(sum(allow_scores) / max(1, len(allow_scores)), 4) if allow_scores else 0.0
    resolution = "review"
    if deny_score >= block_thr and deny_score >= allow_score + margin:
        resolution = "block"
    elif allow_score >= allow_thr and allow_score >= deny_score + margin:
        resolution = "allow"
    return {
        "per_source_confidence": out_src,
        "deny_score": deny_score,
        "allow_score": allow_score,
        "conflicts": int(conflicts),
        "resolution": resolution,
        "thresholds": {"block": float(block_thr), "allow": float(allow_thr), "margin": float(margin)},
        "ioc_type_counts": by_type_counts,
    }


def _sandbox_ioc_stage(enrichment: Dict[str, Any], detonation: Dict[str, Any], ioc_quality: Dict[str, Any]) -> Dict[str, Any]:
    enr = enrichment if isinstance(enrichment, dict) else {}
    det = detonation if isinstance(detonation, dict) else {}
    iq = ioc_quality if isinstance(ioc_quality, dict) else {}
    findings = list(det.get("findings") or [])
    return {
        "stage": "sandbox_ioc_fusion",
        "provider": str(det.get("provider") or "none"),
        "detonation_malicious": bool(det.get("malicious")),
        "detonation_score": float(det.get("score") or 0.0),
        "detonation_findings": findings[:20],
        "ioc_malicious_hits": int(enr.get("malicious_hits") or 0),
        "ioc_conflicts": int(iq.get("conflicts") or 0),
        "ioc_deny_score": float(iq.get("deny_score") or 0.0),
        "ioc_allow_score": float(iq.get("allow_score") or 0.0),
        "resolution": str(iq.get("resolution") or "review"),
    }


def _build_explainability_card(
    *,
    verdict: Dict[str, Any],
    extracted: Dict[str, Any],
    artifact_intel: Dict[str, Any] | None,
    ioc_quality: Dict[str, Any] | None,
    semantic_bec: Dict[str, Any] | None,
    yara_scan: Dict[str, Any] | None,
    ransomware_artifact: Dict[str, Any] | None,
    dmarc_fail: bool,
) -> Dict[str, Any]:
    v = verdict if isinstance(verdict, dict) else {}
    reasons = [str(x) for x in (v.get("reasons") or []) if str(x or "").strip()]
    route = str(v.get("route") or "auto_resolve")
    action = str(v.get("verdict_action") or "allow")
    severity = str(v.get("severity") or "info")
    inds = [i for i in (v.get("indicators") or []) if isinstance(i, dict)]
    top_types = [str((i or {}).get("type") or "") for i in inds if str((i or {}).get("type") or "").strip()][:12]

    contributions = []
    try:
        score = ((artifact_intel or {}).get("signal_scores") if isinstance(artifact_intel, dict) else {}) or {}
        contrib = list(score.get("contributions") or [])
        for c in contrib[:10]:
            if isinstance(c, dict):
                contributions.append(
                    {
                        "feature": str(c.get("type") or c.get("feature") or "unknown"),
                        "weight": float(c.get("weight") or c.get("score") or 0.0),
                        "source": "artifact_intel",
                    }
                )
    except Exception:
        contributions = []
    if not contributions:
        for t in top_types[:10]:
            contributions.append({"feature": t, "weight": 1.0, "source": "indicator"})

    why_flagged = reasons[:8] if reasons else ["no_high_risk_reasons"]
    if route == "security_review":
        why_not_blocked = "Not applicable: routed to security review due to fail-closed/high-confidence controls."
    elif route == "human_review":
        why_not_blocked = "Not fully blocked because controls indicate risk but do not meet hard-block/fail-closed threshold."
    else:
        why_not_blocked = "Not blocked because hard-fail controls were not triggered and policy/trust gates allowed resolution."

    card = {
        "decision": {
            "severity": severity,
            "route": route,
            "verdict_action": action,
            "escalation": str(v.get("escalation") or "none"),
        },
        "why_flagged": why_flagged,
        "why_not_blocked": why_not_blocked,
        "top_contributing_features": contributions[:10],
        "controls_evaluated": {
            "hard_security_triggered": bool((v.get("evidence_snapshot") or {}).get("hard_security_triggered")),
            "oob_verification_required": bool((v.get("evidence_snapshot") or {}).get("oob_verification_required")),
            "dmarc_fail": bool(dmarc_fail),
            "ioc_resolution": str((ioc_quality or {}).get("resolution") or "review"),
            "semantic_bec_score": float((semantic_bec or {}).get("score") or 0.0),
            "yara_match_count": int((yara_scan or {}).get("match_count") or 0),
            "ransomware_signal_count": int((ransomware_artifact or {}).get("signal_count") or 0),
        },
    }
    card["analyst_summary"] = (
        f"Flagged due to {', '.join(why_flagged[:3])}. "
        f"Final route is {route} with action {action}."
    )
    return card


# Forensics snapshots extracted to security/email_forensics_snapshots.py (session-2 decomposition).
# Re-exported so the orchestrator's internal calls resolve unchanged.
from src.app.security.email_forensics_snapshots import (  # noqa: E402
    _attachment_baseline_diff_snapshot,
    _attachment_forensics_snapshot,
    _attachment_visual_diff_snapshot,
    _sender_infrastructure_snapshot,
)


# Finding normalization/ranking/compliance-mapping + agent boundaries extracted to
# security/email_findings.py (session-3 decomposition). Re-exported for the orchestrator.
from src.app.security.email_findings import (  # noqa: E402
    _artifact_evidence_refs,
    _artifact_finding_category,
    _artifact_provenance_rows,
    _claim_contract_for_finding,
    _confidence_band,
    _dedupe_ranked_findings,
    _email_agent_boundaries,
    _finding_agentic_tags,
    _finding_compliance_mapping,
    _finding_rank_score,
    _finding_source_toolset,
    _is_benign_comment_only_vba_artifact,
    _normalize_finding,
)


# Business bundle + drilldown + structured-finding decoration extracted to
# security/email_business_bundle.py (session-4 decomposition). Re-exported for the orchestrator.
from src.app.security.email_business_bundle import (  # noqa: E402
    _decorate_structured_findings,
    _finding_business_bundle,
    _hidden_payload_drilldown,
)


# Action policy (canonical names + build + playbook enforcement) extracted to
# security/email_action_policy.py (session-5 decomposition). Re-exported for the orchestrator.
from src.app.security.email_action_policy import (  # noqa: E402
    _build_action_policy,
    _canonical_action_name,
    _enforce_playbook_actions,
)


# Structured-findings builder + pre-agent-gate + agent-runs audit extracted to
# security/email_structured_findings.py (session-6 decomposition). Re-exported for the orchestrator.
from src.app.security.email_structured_findings import (  # noqa: E402
    _build_agent_runs_audit,
    _build_pre_agent_gate_snapshot,
    _build_structured_findings,
)


def _persist_incident(
    *,
    tenant_id: str | None,
    provider: str | None,
    message_id: str | None,
    conversation_id: str | None,
    supplier_key: str | None,
    ticket_id: str | None,
    severity: str,
    risk_band: str | None,
    tags: list[str],
    reasons: list[str],
    evidence_snapshot: dict,
    playbook: dict | None,
    ticket_created: bool,
    ticket_rate_limited: bool,
    ticket_deduped: bool,
) -> str | None:
    import json
    import uuid
    from sqlalchemy import text

    from src.app.models.db import db_session

    inc_id = f"esi-{uuid.uuid4().hex}"
    insert_full_stmt = text(
        """
        INSERT INTO email_security_incidents
        (id, tenant_id, provider, supplier_key_hash, conversation_id_hash, message_id_hash, ticket_id,
         severity, risk_band, tags_json, reasons_json, evidence_json,
         playbook_id, playbook_title, ticket_created, ticket_rate_limited, ticket_deduped)
        VALUES
        (:id, :tenant_id, :provider, :supplier_key_hash, :conversation_id_hash, :message_id_hash, :ticket_id,
         :severity, :risk_band, :tags_json, :reasons_json, :evidence_json,
         :playbook_id, :playbook_title, :ticket_created, :ticket_rate_limited, :ticket_deduped)
        """
    )
    insert_min_stmt = text(
        """
        INSERT INTO email_security_incidents
        (id, severity, tags_json, reasons_json, evidence_json)
        VALUES
        (:id, :severity, :tags_json, :reasons_json, :evidence_json)
        """
    )
    payload = {
        "id": inc_id,
        "tenant_id": tenant_id,
        "provider": provider,
        "supplier_key_hash": _hash16(supplier_key),
        "conversation_id_hash": _hash16(conversation_id),
        "message_id_hash": _hash16(message_id),
        "ticket_id": ticket_id,
        "severity": severity,
        "risk_band": risk_band,
        "tags_json": json.dumps(tags or [], ensure_ascii=False),
        "reasons_json": json.dumps(reasons or [], ensure_ascii=False),
        "evidence_json": json.dumps(evidence_snapshot or {}, ensure_ascii=False),
        "playbook_id": (playbook or {}).get("id") if isinstance(playbook, dict) else None,
        "playbook_title": (playbook or {}).get("title") if isinstance(playbook, dict) else None,
        "ticket_created": 1 if ticket_created else 0,
        "ticket_rate_limited": 1 if ticket_rate_limited else 0,
        "ticket_deduped": 1 if ticket_deduped else 0,
    }
    try:
        with db_session() as db:
            # Ensure incident table exists across DB backends/environments.
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS email_security_incidents (
                      id TEXT PRIMARY KEY,
                      tenant_id TEXT,
                      provider TEXT,
                      supplier_key_hash TEXT,
                      conversation_id_hash TEXT,
                      message_id_hash TEXT,
                      ticket_id TEXT,
                      severity TEXT NOT NULL,
                      risk_band TEXT,
                      tags_json TEXT NOT NULL,
                      reasons_json TEXT NOT NULL,
                      evidence_json TEXT NOT NULL,
                      playbook_id TEXT,
                      playbook_title TEXT,
                      ticket_created INTEGER NOT NULL DEFAULT 0,
                      ticket_rate_limited INTEGER NOT NULL DEFAULT 0,
                      ticket_deduped INTEGER NOT NULL DEFAULT 0,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    INSERT INTO email_security_incidents
                    (id, tenant_id, provider, supplier_key_hash, conversation_id_hash, message_id_hash, ticket_id,
                     severity, risk_band, tags_json, reasons_json, evidence_json,
                     playbook_id, playbook_title, ticket_created, ticket_rate_limited, ticket_deduped, created_at)
                    VALUES
                    (:id, :tenant_id, :provider, :supplier_key_hash, :conversation_id_hash, :message_id_hash, :ticket_id,
                     :severity, :risk_band, :tags_json, :reasons_json, :evidence_json,
                     :playbook_id, :playbook_title, :ticket_created, :ticket_rate_limited, :ticket_deduped, CURRENT_TIMESTAMP)
                    """
                ),
                payload,
            )
            db.commit()
    except Exception:
        # Best-effort fallback for schema drift: insert only known columns.
        try:
            with db_session() as db:
                cols: list[str] = []
                try:
                    rows = db.execute(text("PRAGMA table_info(email_security_incidents)")).fetchall()
                    cols = [str(r[1]) for r in (rows or []) if len(r) > 1]
                except Exception:
                    cols = []
                if not cols:
                    # PostgreSQL fallback: PRAGMA is SQLite-only
                    try:
                        rows = db.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns"
                                " WHERE table_name = 'email_security_incidents'"
                                "   AND table_schema IN (current_schema(), 'public')"
                            )
                        ).fetchall()
                        cols = [str(r[0]) for r in (rows or [])]
                    except Exception:
                        cols = []
                if not cols:
                    return None
                colset = set(str(c) for c in cols)
                full_cols = {
                    "id", "tenant_id", "provider", "supplier_key_hash", "conversation_id_hash", "message_id_hash", "ticket_id",
                    "severity", "risk_band", "tags_json", "reasons_json", "evidence_json",
                    "playbook_id", "playbook_title", "ticket_created", "ticket_rate_limited", "ticket_deduped",
                }
                minimal_cols = {"id", "severity", "tags_json", "reasons_json", "evidence_json"}
                if full_cols.issubset(colset):
                    db.execute(insert_full_stmt, payload)
                elif minimal_cols.issubset(colset):
                    db.execute(insert_min_stmt, payload)
                else:
                    return None
                db.commit()
        except Exception:
            # Best-effort persistence (schema may be absent in SQLite-only envs).
            return None
    return inc_id


# DMARC parsing + BEC heuristics extracted to security/email_dmarc.py (session-1 decomposition).
# Re-exported so `from src.app.security.email_security import parse_dmarc_aggregate` (and the other
# names) keep resolving — call sites and tests are untouched.
from src.app.security.email_dmarc import (  # noqa: E402
    _parse_dmarc_xml,
    detect_bec_indicators,
    parse_dmarc_aggregate,
    process_dmarc_report,
)


def evaluate_email_security(email: Dict[str, Any], tenant_id: str | None = None) -> Dict[str, Any]:
    """Evaluate an email for BEC/security signals, emit telemetry, and ticket with rate-limit.

    Minimal expected 'email' keys: message_id, from_addr, reply_to, subject, body, attachments (optional list).
    """
    try:
        flags_path = os.getenv("FEATURE_FLAGS_PATH") or get_settings().feature_flags_path
        ff = load_feature_flags(flags_path) or {}
    except Exception:
        ff = {}
    thr = ff.get("SECURITY_THRESHOLDS", {})
    rt_thr = {}
    try:
        rt_thr = get_runtime_thresholds(tenant_id)
    except Exception:
        rt_thr = {}
    rt_cfg = ff.get("TICKET_RATE_LIMIT", {"enabled": False, "per_min": 5})
    per_min = int(rt_cfg.get("per_min", 5))
    enabled = bool(rt_cfg.get("enabled", False))
    runtime_errors: list[dict[str, Any]] = []

    # Normalize auth fields from both flat and nested payload styles.
    try:
        auth_spf = email.get("spf") if isinstance(email.get("spf"), dict) else {}
        auth_dkim = email.get("dkim") if isinstance(email.get("dkim"), dict) else {}
        auth_dmarc = email.get("dmarc") if isinstance(email.get("dmarc"), dict) else {}
        if not email.get("spf_result"):
            email["spf_result"] = auth_spf.get("result")
        if not email.get("dkim_result"):
            email["dkim_result"] = auth_dkim.get("result")
        if not email.get("dmarc_result"):
            email["dmarc_result"] = auth_dmarc.get("result")
        if not email.get("dmarc_policy"):
            email["dmarc_policy"] = auth_dmarc.get("policy") or auth_dmarc.get("p")
        if "dmarc_fail" not in email and str(email.get("dmarc_result") or "").lower() in ("fail", "reject", "quarantine"):
            email["dmarc_fail"] = True
    except Exception:
        pass

    # Intake-only normalization (no detection). Keeps downstream logic deterministic.
    try:
        email, intake_meta = normalize_email_intake(email)
    except Exception:
        intake_meta = {"gate": "intake_only", "error": "normalize_failed"}
    # Invisible-char deception surfaced by intake → typed indicators. A bidi override in an address
    # or subject is a strong spoof signal (hides the real address behind a rendered one); zero-width
    # is a weaker obfuscation marker. The indicators fold into the verdict below.
    _intake_obf_indicators = []
    if intake_meta.get("obfuscation_bidi_override"):
        _intake_obf_indicators.append({"type": "obfuscation_bidi_override", "severity": "high",
                                       "detail": "bidi override characters hide the rendered text direction"})
    if intake_meta.get("obfuscation_zero_width"):
        _intake_obf_indicators.append({"type": "obfuscation_zero_width", "severity": "medium",
                                       "detail": "zero-width characters embedded in email fields"})

    # Live DNS verification of SPF/DMARC/DKIM — non-authoritative, adds discrepancy indicators.
    dns_auth_result: dict[str, Any] = {}
    try:
        dns_auth_result = run_dns_auth_checks_parallel(email)
        dns_indicators = list(dns_auth_result.get("discrepancy_indicators") or [])
        if dns_indicators:
            logger.info(
                "DNS auth discrepancy found for domain=%s indicators=%d",
                dns_auth_result.get("domain"),
                len(dns_indicators),
            )
    except Exception as _dns_exc:
        logger.debug("DNS auth check failed: %s", _dns_exc)
        dns_auth_result = {"skipped": True, "error": str(_dns_exc)[:120]}

    # ── Lookalike domain detection (0ms — pure string math) ──
    lookalike_result: dict[str, Any] = {}
    try:
        _from_domain = str(email.get("from_addr") or "").lower()
        if "@" in _from_domain:
            _from_domain = _from_domain.rsplit("@", 1)[-1].split(">")[0].strip()
        _vendor_domain = str(email.get("vendor_domain") or "").lower().strip()
        _known_domains = [d for d in [_vendor_domain] if d and "." in d]
        # Also add domains from known brand list
        _BRAND_DOMAINS = [
            "amazon.com", "ebay.com", "paypal.com", "stripe.com", "shopify.com",
            "microsoft.com", "google.com", "apple.com", "facebook.com",
        ]
        _known_domains += _BRAND_DOMAINS

        _HOMOGLYPHS = {"rn": "m", "0": "o", "1": "l", "vv": "w", "ii": "u", "cl": "d"}

        def _normalize_glyphs(s: str) -> str:
            for glyph, normal in _HOMOGLYPHS.items():
                s = s.replace(glyph, normal)
            return s

        def _levenshtein(a: str, b: str) -> int:
            if a == b:
                return 0
            if not a:
                return len(b)
            if not b:
                return len(a)
            prev = list(range(len(b) + 1))
            for i, ca in enumerate(a, 1):
                curr = [i]
                for j, cb in enumerate(b, 1):
                    curr.append(min(prev[j] + 1, curr[-1] + 1, prev[j - 1] + (0 if ca == cb else 1)))
                prev = curr
            return prev[-1]

        _lookalike_hits: list[dict[str, Any]] = []
        if _from_domain:
            _norm_from = _normalize_glyphs(_from_domain)
            for known in _known_domains:
                if not known or known == _from_domain:
                    continue
                # Strip TLD for comparison (amazon.com → amazon)
                _from_base = _from_domain.rsplit(".", 1)[0] if "." in _from_domain else _from_domain
                _known_base = known.rsplit(".", 1)[0] if "." in known else known
                _norm_from_base = _normalize_glyphs(_from_base)
                dist = _levenshtein(_norm_from_base, _known_base)
                homoglyph_exact_match = (_norm_from_base == _known_base and _from_base != _known_base)
                if homoglyph_exact_match or 1 <= dist <= 2:
                    _lookalike_hits.append({
                        "from_domain": _from_domain,
                        "resembles": known,
                        "edit_distance": (1 if homoglyph_exact_match and dist == 0 else dist),
                        "homoglyph_normalized": _norm_from != _from_domain,
                    })
        if _lookalike_hits:
            lookalike_result = {
                "detected": True,
                "hits": _lookalike_hits,
                "severity": "high" if any(h["edit_distance"] == 1 for h in _lookalike_hits) else "medium",
            }
            logger.warning(
                "Lookalike domain detected: from=%s hits=%s",
                _from_domain, [h["resembles"] for h in _lookalike_hits],
            )
    except Exception as _lk_exc:
        logger.debug("Lookalike domain check failed: %s", _lk_exc)
        lookalike_result = {}

    # ── Thread hijacking detection (0ms — reply chain analysis) ──
    thread_hijack_result: dict[str, Any] = {}
    try:
        _reply_chain_id = str(email.get("reply_chain_id") or "").strip()
        _prior_reply_chain_id = str(email.get("prior_reply_chain_id") or "").strip()
        _from_addr = str(email.get("from_addr") or "").lower()
        if _reply_chain_id and _prior_reply_chain_id and _reply_chain_id == _prior_reply_chain_id:
            # Same thread — check if sender domain changed since prior message
            _from_domain_now = _from_addr.rsplit("@", 1)[-1].split(">")[0].strip() if "@" in _from_addr else ""
            # We don't have prior sender stored, but vendor_domain acts as the expected domain
            if _vendor_domain and _from_domain_now and _from_domain_now != _vendor_domain:
                thread_hijack_result = {
                    "detected": True,
                    "from_domain": _from_domain_now,
                    "expected_domain": _vendor_domain,
                    "thread_id": _reply_chain_id,
                    "reason": "Sender domain changed mid-thread — classic BEC thread hijack pattern",
                    "severity": "high",
                }
                logger.warning(
                    "Thread hijack suspected: thread=%s from_domain=%s expected=%s",
                    _reply_chain_id, _from_domain_now, _vendor_domain,
                )
    except Exception as _th_exc:
        logger.debug("Thread hijack check failed: %s", _th_exc)
        thread_hijack_result = {}

    # Strict ingest controls before deep parsing: MIME/ext/size/archive/AV.
    try:
        email, ingest_gate_meta = strict_attachment_ingest_gate(email)
    except Exception:
        ingest_gate_meta = {"gate": "strict_attachment_ingest", "blocked": False, "error": "ingest_gate_failed"}

    # Accept raw base64 attachment bytes in the evaluate path and hydrate deterministic metadata/text.
    try:
        email = hydrate_attachments_from_bytes(email, tenant_id=tenant_id)
    except Exception:
        email = dict(email)

    # OCR text sanitization + QR URL allowlist enforcement before any model-assisted processing.
    try:
        email, ocr_sanitization_meta = sanitize_attachment_ocr_for_llm(email)
    except Exception:
        ocr_sanitization_meta = {"gate": "ocr_qr_sanitization", "blocked_qr_url_count": 0, "error": "ocr_sanitize_failed"}

    content_classification = _classify_email_content_mode(email)

    extracted = extract_indicators(email, tenant_id=tenant_id)
    try:
        extracted.setdefault("meta", {})["content_classification"] = content_classification
    except Exception:
        pass
    # Fold the intake obfuscation indicators (zero-width / bidi override) into the indicator set.
    if _intake_obf_indicators:
        extracted["indicators"] = list(extracted.get("indicators") or []) + _intake_obf_indicators
    # Fold steg signals from hydrated attachments into extracted indicators so
    # they propagate into verdict, framework_correlation, DREAD, and playbook.
    try:
        _steg_atts = [a for a in (email.get("attachments") or []) if bool((a or {}).get("steg_suspicious"))]
        if _steg_atts:
            _existing_types = {str((i or {}).get("type") or "") for i in (extracted.get("indicators") or [])}
            if "steg_suspicious" not in _existing_types:
                extracted["indicators"] = list(extracted.get("indicators") or []) + [
                    {
                        "type": "steg_suspicious",
                        "value": True,
                        "reason": (
                            f"steg_score={_steg_atts[0].get('steg_score', 0):.3f}; "
                            f"attachment={_steg_atts[0].get('name') or 'unknown'}"
                        ),
                        "attachment_count": len(_steg_atts),
                    }
                ]
                # Also flag steg_score_elevated for OWASP LLM02 mapping
                if "steg_score_elevated" not in _existing_types:
                    extracted["indicators"] = list(extracted.get("indicators") or []) + [
                        {"type": "steg_score_elevated", "value": True, "reason": "steg_suspicious attachment present"}
                    ]
    except Exception:
        pass
    yara_scan: Dict[str, Any] = {"engine": "disabled", "rules_loaded": 0, "match_count": 0, "matches": []}
    try:
        yara_scan = scan_email_yara(email, extracted)
        y_matches = list(yara_scan.get("matches") or [])
        existing_types = {str((i or {}).get("type") or "") for i in (extracted.get("indicators") or [])}
        for m in y_matches:
            indicator_type = str(m.get("indicator_type") or "").strip()
            if indicator_type and indicator_type not in existing_types:
                extracted["indicators"] = list(extracted.get("indicators") or []) + [
                    {
                        "type": indicator_type,
                        "value": True,
                        "reason": f"YARA rule matched: {m.get('rule_id')}:{m.get('rule_name')}",
                    }
                ]
                existing_types.add(indicator_type)
        extracted.setdefault("meta", {})["yara"] = {
            "engine": yara_scan.get("engine"),
            "rules_loaded": int(yara_scan.get("rules_loaded") or 0),
            "match_count": int(yara_scan.get("match_count") or 0),
        }
    except Exception:
        pass
    semantic_bec: Dict[str, Any] = {
        "enabled": False,
        "score": 0.0,
        "detected": False,
        "review_threshold": 0.72,
        "security_threshold": 0.82,
        "provider": "none",
        "intent_scores": {},
        "matched_intent": None,
        "matched_seed": None,
    }
    try:
        semantic_bec = score_semantic_bec(email)
        if bool(semantic_bec.get("detected")):
            extracted["indicators"] = list(extracted.get("indicators") or []) + [
                {
                    "type": "semantic_bec_signal",
                    "value": float(semantic_bec.get("score") or 0.0),
                    "reason": f"Semantic BEC score {float(semantic_bec.get('score') or 0.0):.3f}",
                }
            ]
        extracted.setdefault("meta", {})["semantic_bec"] = semantic_bec
    except Exception:
        pass
    # AI-authored / synthetic-text stylometry — SHADOW by default (computed + logged, NOT scored)
    # because it false-positives on legitimate templated/formal vendor mail. Only when
    # EMAIL_AI_TEXT_ENFORCED is set AND another BEC-ish signal is present does it become a scoring
    # indicator — never a standalone escalation. Calibrate in shadow before flipping.
    try:
        import os as _os_ai
        from src.app.security.email_ai_authorship import score_ai_authorship
        _ai_auth = score_ai_authorship(str(email.get("body") or ""))
        extracted.setdefault("meta", {})["ai_authorship"] = _ai_auth
        _ai_enforce = str(_os_ai.getenv("EMAIL_AI_TEXT_ENFORCED", "0")).strip().lower() in ("1", "true", "yes", "on")
        _bec_context = bool(semantic_bec.get("detected")) or any(
            str((i or {}).get("type") or "") in ("bank_change_request", "reply_to_mismatch", "lookalike_domain",
                                                 "urgency", "invoice_redirect")
            for i in (extracted.get("indicators") or [])
        )
        if _ai_enforce and bool(_ai_auth.get("detected")) and _bec_context:
            extracted["indicators"] = list(extracted.get("indicators") or []) + [{
                "type": "ai_generated_text_signal",
                "value": float(_ai_auth.get("score") or 0.0),
                "reason": f"AI-authored stylometry {float(_ai_auth.get('score') or 0.0):.2f} alongside BEC context",
            }]
    except Exception:
        pass
    thread_graph: Dict[str, Any] = {
        "thread_key": None,
        "sender_domain": None,
        "previous_sender_domain": None,
        "gap_hours": 0.0,
        "silence_threshold_hours": 168,
        "reentry_after_silence": False,
        "sender_domain_drift": False,
        "indicator_count": 0,
        "indicators": [],
        "message_count_before": 0,
        "distinct_sender_domains": [],
    }
    try:
        thread_graph = analyze_thread_conversation_graph(email, tenant_id=tenant_id)
        tg_inds = list(thread_graph.get("indicators") or [])
        if tg_inds:
            extracted["indicators"] = list(extracted.get("indicators") or []) + tg_inds
        extracted.setdefault("meta", {})["thread_graph"] = {
            "thread_key": thread_graph.get("thread_key"),
            "reentry_after_silence": bool(thread_graph.get("reentry_after_silence")),
            "sender_domain_drift": bool(thread_graph.get("sender_domain_drift")),
            "gap_hours": float(thread_graph.get("gap_hours") or 0.0),
            "silence_threshold_hours": int(thread_graph.get("silence_threshold_hours") or 0),
        }
    except Exception:
        pass

    # Inject DNS discrepancy indicators discovered above.
    try:
        dns_inds = list(dns_auth_result.get("discrepancy_indicators") or [])
        if dns_inds:
            extracted["indicators"] = list(extracted.get("indicators") or []) + dns_inds
        extracted.setdefault("meta", {})["dns_auth"] = {
            "skipped": bool(dns_auth_result.get("skipped")),
            "domain": dns_auth_result.get("domain"),
            "spf_available": bool((dns_auth_result.get("spf") or {}).get("available")),
            "dmarc_available": bool((dns_auth_result.get("dmarc") or {}).get("available")),
            "dmarc_policy": (dns_auth_result.get("dmarc") or {}).get("policy"),
            "dkim_available": bool((dns_auth_result.get("dkim") or {}).get("available")),
            "discrepancy_count": len(dns_inds),
        }
    except Exception:
        pass

    header_forensics = {}
    try:
        header_forensics = analyze_email_headers(email)
        h_risk = float(header_forensics.get("risk_score") or 0.0)
        h_inds = []
        if bool(header_forensics.get("timing_anomaly")):
            h_inds.append({"type": "received_chain_timing_anomaly", "value": True, "reason": "Received chain timestamp ordering anomaly"})
        if bool(header_forensics.get("header_injection_detected")):
            h_inds.append({"type": "header_injection_detected", "value": True, "reason": "CRLF/null/oversized header anomaly"})
        if bool(header_forensics.get("message_id_reuse")):
            h_inds.append({"type": "message_id_reuse_detected", "value": True, "reason": "Message-ID replay/reuse detected"})
        if bool(header_forensics.get("message_id_domain_mismatch")):
            h_inds.append({"type": "message_id_domain_mismatch", "value": True, "reason": "Message-ID domain differs from From domain"})
        if h_risk >= float((thr or {}).get("HEADER_FORENSICS_WARN_THRESHOLD", 0.45)):
            h_inds.append({"type": "header_forensics_risk", "value": h_risk, "reason": f"Header forensics risk {h_risk:.2f}"})
        if h_inds:
            extracted["indicators"] = list(extracted.get("indicators") or []) + h_inds
        extracted.setdefault("meta", {})["header_forensics"] = header_forensics
    except Exception:
        header_forensics = {}
    try:
        extra_inds = []
        if bool((ingest_gate_meta or {}).get("blocked")):
            extra_inds.append(
                {
                    "type": "ingest_gate_blocked_attachment",
                    "value": True,
                    "reason": ",".join((ingest_gate_meta or {}).get("block_reasons") or ["attachment_blocked"]),
                }
            )
        if int((ocr_sanitization_meta or {}).get("blocked_qr_url_count") or 0) > 0:
            extra_inds.append(
                {
                    "type": "qr_url_not_allowlisted",
                    "value": True,
                    "reason": "Attachment OCR/QR contains non-allowlisted URLs",
                }
            )
        if int((ocr_sanitization_meta or {}).get("prompt_instruction_hits") or 0) > 0:
            extra_inds.append(
                {
                    "type": "ocr_prompt_instruction_sanitized",
                    "value": int((ocr_sanitization_meta or {}).get("prompt_instruction_hits") or 0),
                    "reason": "Untrusted OCR prompt-instruction text was sanitized",
                }
            )
        if extra_inds:
            extracted["indicators"] = list(extracted.get("indicators") or []) + extra_inds
    except Exception:
        pass
    artifact_intel = {}
    try:
        artifact_intel = analyze_email_artifacts(email)
        if isinstance(artifact_intel, dict):
            ai_inds = list(artifact_intel.get("indicators") or [])
            if ai_inds:
                extracted["indicators"] = list(extracted.get("indicators") or []) + ai_inds
            try:
                m = extracted.setdefault("meta", {})
                if isinstance(m, dict):
                    m["artifact_intel"] = {
                        "parsed_fields": artifact_intel.get("parsed_fields") or {},
                        "baseline_checks": artifact_intel.get("baseline_checks") or {},
                        "forensics_details": artifact_intel.get("forensics_details") or {},
                        "signal_scores": artifact_intel.get("signal_scores") or {},
                    }
            except Exception:
                pass
    except Exception:
        artifact_intel = {}
    ransomware_artifact = {
        "mode": "artifact_only_pre_execution",
        "signal_count": 0,
        "signals": {},
        "indicators": [],
        "coverage_limits": ransomware_coverage_limits(),
    }
    try:
        ransomware_artifact = analyze_ransomware_artifacts(email)
        r_inds = list((ransomware_artifact or {}).get("indicators") or [])
        if r_inds:
            extracted["indicators"] = list(extracted.get("indicators") or []) + r_inds
        extracted.setdefault("meta", {})["ransomware_artifact"] = {
            "mode": str((ransomware_artifact or {}).get("mode") or "artifact_only_pre_execution"),
            "signal_count": int((ransomware_artifact or {}).get("signal_count") or 0),
        }
    except Exception:
        ransomware_artifact = {
            "mode": "artifact_only_pre_execution",
            "signal_count": 0,
            "signals": {},
            "indicators": [],
            "coverage_limits": ransomware_coverage_limits(),
        }
    mailbox_compromise = {}
    try:
        mailbox_compromise = analyze_mailbox_compromise(email)
        mc_inds = list((mailbox_compromise or {}).get("indicators") or [])
        if mc_inds:
            extracted["indicators"] = list(extracted.get("indicators") or []) + mc_inds
        extracted.setdefault("meta", {})["mailbox_compromise"] = {
            "risk_score": float((mailbox_compromise or {}).get("risk_score") or 0.0),
            "compromised": bool((mailbox_compromise or {}).get("compromised")),
            "signal_count": int((mailbox_compromise or {}).get("signal_count") or 0),
        }
    except Exception:
        mailbox_compromise = {}
    trust = {}
    try:
        trust = score_sender_trust(email, extracted, tenant_id)
        indicators = list(extracted.get("indicators") or [])
        sender_trust_low_thr = float(
            rt_thr.get("sender_trust_low_threshold", (thr or {}).get("SENDER_TRUST_LOW_THRESHOLD", 0.35))
        )
        if float(trust.get("sender_trust_score") or 0.0) < sender_trust_low_thr:
            indicators.append({"type": "sender_trust_low", "value": trust.get("sender_trust_score"), "reason": "Sender trust below baseline"})
        if float(trust.get("reply_chain_continuity_score") or 0.0) < 0.5:
            indicators.append({"type": "reply_chain_discontinuity", "value": trust.get("reply_chain_continuity_score"), "reason": "Reply-chain continuity low"})
        if float(trust.get("vendor_relationship_confidence") or 0.0) < float((thr or {}).get("VENDOR_CONFIDENCE_LOW_THRESHOLD", 0.4)):
            indicators.append(
                {
                    "type": "vendor_confidence_low",
                    "value": trust.get("vendor_relationship_confidence"),
                    "reason": "Vendor relationship confidence below threshold",
                }
            )
        # §5: Require sender-domain aging before any payment-instruction bypass.
        # If bank-change/payment indicators exist and domain trust age < 30d, force HITL.
        try:
            min_age = int((thr or {}).get("PAYMENT_BYPASS_MIN_DOMAIN_AGE_DAYS", 30) or 30)
        except Exception:
            min_age = 30
        try:
            age_days = int((trust or {}).get("domain_age_days") or 0)
        except Exception:
            age_days = 0
        body_text = str(email.get("body") or "").lower()
        has_payment_token = any(
            tok in body_text
            for tok in (
                "bank account",
                "beneficiary",
                "wire transfer",
                "remit",
                "payment",
                "invoice",
            )
        )
        # Avoid false positives on explicit negation phrases such as
        # "no payment changes" / "no remittance changes".
        has_payment_negation = bool(
            re.search(
                r"(?i)\b(?:no|not|without)\b.{0,24}\b(?:payment|remittance|bank(?:ing)?\s+details?|invoice)\b",
                body_text,
            )
            or re.search(
                r"(?i)\b(?:payment|remittance|bank(?:ing)?\s+details?|invoice)\b.{0,24}\b(?:no|not|without)\b",
                body_text,
            )
        )
        payment_instruction = bool(has_payment_token and not has_payment_negation)
        bank_change_flag = bool(
            str(email.get("bank_fingerprint") or "")
            and str(email.get("proposed_bank_fingerprint") or "")
            and str(email.get("bank_fingerprint") or "") != str(email.get("proposed_bank_fingerprint") or "")
        )
        if (payment_instruction or bank_change_flag) and age_days < min_age:
            indicators.append(
                {
                    "type": "domain_age_insufficient_for_payment_instruction",
                    "value": age_days,
                    "reason": f"Sender domain trust age {age_days}d < required {min_age}d for payment instruction bypass",
                }
            )
        extracted["indicators"] = indicators
        extracted.setdefault("meta", {})["sender_trust"] = trust
    except Exception:
        trust = {}
    # Provider-backed BIMI verification (header + DNS + logo URL checks).
    try:
        bimi = verify_bimi_provider_backed(email)
        extracted.setdefault("meta", {})["bimi_verification"] = bimi
        if bool(bimi.get("verified")):
            extracted["indicators"] = list(extracted.get("indicators") or []) + [
                {"type": "bimi_provider_verified", "value": True, "reason": "BIMI provider, DNS and logo checks passed"}
            ]
        elif bool(bimi.get("failed")):
            extracted["indicators"] = list(extracted.get("indicators") or []) + [
                {"type": "bimi_provider_verification_failed", "value": True, "reason": "BIMI verification failed across provider/DNS/logo checks"}
            ]
        visual = (bimi.get("visual_similarity") if isinstance(bimi, dict) else {}) or {}
        if bool(visual.get("spoof_suspected")):
            extracted["indicators"] = list(extracted.get("indicators") or []) + [
                {
                    "type": "bimi_visual_brand_mismatch",
                    "value": float(visual.get("brand_spoof_score") or 0.0),
                    "reason": "BIMI visual brand similarity indicates possible lookalike spoofing",
                }
            ]
            extracted.setdefault("meta", {})["bimi_visual_similarity"] = visual
    except Exception:
        pass

    # DMARC fail is considered if caller passed a boolean in email["dmarc_fail"]. Default False.
    dmarc_fail = bool(email.get("dmarc_fail", False))
    spf_result = str(email.get("spf_result") or "").lower()
    dkim_result = str(email.get("dkim_result") or "").lower()
    dmarc_result = str(email.get("dmarc_result") or "").lower()
    dmarc_policy = str(email.get("dmarc_policy") or "").lower()
    v = compute_verdict(email, extracted, dmarc_fail=dmarc_fail)
    try:
        y_matches = list((yara_scan or {}).get("matches") or [])
        y_mitre = []
        high_conf = False
        for m in y_matches:
            if float(m.get("confidence") or 0.0) >= 0.85:
                high_conf = True
            corr = m.get("correlation") if isinstance(m.get("correlation"), dict) else {}
            y_mitre.extend([str(x) for x in (corr.get("mitre_attack") or []) if str(x)])
        if y_matches:
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["yara_rule_match_detected"]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + [f"yara:{str(m.get('rule_id') or '').strip().lower()}" for m in y_matches if str(m.get("rule_id") or "").strip()]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + [f"mitre:{m}" for m in y_mitre if m]))
            if high_conf:
                v["severity"] = "error"
                v["route"] = "security_review"
                v["verdict_action"] = "security_review"
                v["escalation"] = "security_middleware"
                v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["yara_high_confidence_match"]))
            elif v.get("route") == "auto_resolve":
                v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
                v["route"] = "human_review"
                v["verdict_action"] = "quarantine"
                v["escalation"] = "human_review"
                v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["yara_review_gate"]))
    except Exception:
        pass
    try:
        sem_score = float((semantic_bec or {}).get("score") or 0.0)
        sem_review = float((semantic_bec or {}).get("review_threshold") or 0.72)
        sem_security = float((semantic_bec or {}).get("security_threshold") or 0.82)
        if sem_score >= sem_security:
            v["severity"] = "error"
            v["route"] = "security_review"
            v["verdict_action"] = "security_review"
            v["escalation"] = "security_middleware"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["semantic_bec_security_threshold"]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + ["semantic_bec", "semantic_bec:high"]))
        elif sem_score >= sem_review and v.get("route") == "auto_resolve":
            v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
            v["route"] = "human_review"
            v["verdict_action"] = "quarantine"
            v["escalation"] = "human_review"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["semantic_bec_review_threshold"]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + ["semantic_bec", "semantic_bec:review"]))
        v["semantic_bec_score"] = round(sem_score, 4)
    except Exception:
        pass
    # Lift the shadow AI-authorship reading to the top-level result (observable even when it does
    # not score the verdict) — same pattern as semantic_bec_score.
    try:
        _ai = (extracted.get("meta") or {}).get("ai_authorship")
        if isinstance(_ai, dict):
            v["ai_authorship"] = _ai
    except Exception:
        pass
    try:
        r_types = {str((i or {}).get("type") or "") for i in (v.get("indicators") or [])}
        strong = {
            "ransomware_shadow_copy_deletion_command",
            "ransomware_office_to_script_chain_indicator",
        }
        weak = {
            "ransomware_attachment_entropy_hint",
            "ransomware_canary_targeting_pattern",
        }
        if r_types & strong:
            v["severity"] = "error"
            v["route"] = "security_review"
            v["verdict_action"] = "security_review"
            v["escalation"] = "security_middleware"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["ransomware_artifact_strong_signal"]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + ["ransomware_artifact", "ransomware_artifact:strong"]))
        elif (r_types & weak) and v.get("route") == "auto_resolve":
            v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
            v["route"] = "human_review"
            v["verdict_action"] = "quarantine"
            v["escalation"] = "human_review"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["ransomware_artifact_review_signal"]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + ["ransomware_artifact", "ransomware_artifact:review"]))
    except Exception:
        pass
    try:
        reentry = bool(thread_graph.get("reentry_after_silence"))
        drift = bool(thread_graph.get("sender_domain_drift"))
        if reentry and drift:
            v["severity"] = "error"
            v["route"] = "security_review"
            v["verdict_action"] = "security_review"
            v["escalation"] = "security_middleware"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["thread_reentry_sender_drift_combo"]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + ["thread_graph", "thread_graph:drift", "thread_graph:reentry"]))
        elif (reentry or drift) and v.get("route") == "auto_resolve":
            v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
            v["route"] = "human_review"
            v["verdict_action"] = "quarantine"
            v["escalation"] = "human_review"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["thread_graph_review"]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + ["thread_graph"]))
    except Exception:
        pass
    try:
        bimi_visual = ((extracted.get("meta") or {}).get("bimi_visual_similarity") if isinstance(extracted, dict) else {}) or {}
        spoof_score = float(bimi_visual.get("brand_spoof_score") or 0.0)
        if bool(bimi_visual.get("spoof_suspected")) and spoof_score >= 0.75:
            if v.get("route") == "auto_resolve":
                v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
                v["route"] = "human_review"
                v["verdict_action"] = "quarantine"
                v["escalation"] = "human_review"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["bimi_visual_brand_similarity_spoof"]))
            v["tags"] = list(dict.fromkeys((v.get("tags") or []) + ["bimi_visual_similarity", "brand_spoof"]))
    except Exception:
        pass
    try:
        h_risk = float((header_forensics or {}).get("risk_score") or 0.0)
    except Exception:
        h_risk = 0.0
    # IOC confidence + conflict resolution thresholds
    ioc_cfg = (thr or {}) if isinstance(thr, dict) else {}
    ioc_quality = _ioc_quality(
        list(v.get("iocs") or []),
        block_thr=float(ioc_cfg.get("IOC_BLOCK_THRESHOLD", 0.8)),
        allow_thr=float(ioc_cfg.get("IOC_ALLOW_THRESHOLD", 0.75)),
        margin=float(ioc_cfg.get("IOC_CONFLICT_MARGIN", 0.1)),
    )
    if ioc_quality.get("resolution") == "block":
        v["severity"] = "error"
        v["route"] = "security_review"
        v["verdict_action"] = "security_review"
        v["escalation"] = "security_middleware"
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["ioc_confidence_block_threshold_met"]))
    elif ioc_quality.get("resolution") == "review" and v.get("route") == "auto_resolve":
        v["severity"] = "warning"
        v["route"] = "human_review"
        v["verdict_action"] = "quarantine"
        v["escalation"] = "human_review"
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["ioc_confidence_conflict_review"]))
    # Intake gate hard-stop: deny clearly unsafe attachments before downstream actions.
    if bool((ingest_gate_meta or {}).get("blocked")):
        v["severity"] = "error"
        v["route"] = "security_review"
        v["verdict_action"] = "security_review"
        v["escalation"] = "security_middleware"
        v["reasons"] = list(
            dict.fromkeys(
                (v.get("reasons") or [])
                + ["ingest_gate_blocked_attachment"]
                + [str(x) for x in ((ingest_gate_meta or {}).get("global_reasons") or [])]
            )
        )
    # Header forensics can escalate suspicious sender/header tampering patterns.
    try:
        hdr_warn = float((thr or {}).get("HEADER_FORENSICS_WARN_THRESHOLD", 0.45))
        hdr_err = float((thr or {}).get("HEADER_FORENSICS_ERROR_THRESHOLD", 0.75))
    except Exception:
        hdr_warn, hdr_err = 0.45, 0.75
    if h_risk >= hdr_err:
        v["severity"] = "error"
        v["route"] = "security_review"
        v["verdict_action"] = "security_review"
        v["escalation"] = "security_middleware"
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["header_forensics_high_risk"]))
    elif h_risk >= hdr_warn and v.get("route") == "auto_resolve":
        v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
        v["route"] = "human_review"
        v["verdict_action"] = "quarantine"
        v["escalation"] = "human_review"
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["header_forensics_review"]))
    try:
        mc_risk = float((mailbox_compromise or {}).get("risk_score") or 0.0)
        mc_warn = float((thr or {}).get("MAILBOX_COMPROMISE_WARN_THRESHOLD", 0.45))
        mc_err = float((thr or {}).get("MAILBOX_COMPROMISE_ERROR_THRESHOLD", 0.7))
        if bool((mailbox_compromise or {}).get("compromised")) or mc_risk >= mc_err:
            v["severity"] = "error"
            v["route"] = "security_review"
            v["verdict_action"] = "security_review"
            v["escalation"] = "security_middleware"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["mailbox_compromise_high_risk"]))
        elif mc_risk >= mc_warn and v.get("route") == "auto_resolve":
            v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
            v["route"] = "human_review"
            v["verdict_action"] = "quarantine"
            v["escalation"] = "human_review"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["mailbox_compromise_review"]))
    except Exception:
        pass
    if int((ocr_sanitization_meta or {}).get("blocked_qr_url_count") or 0) > 0:
        if v.get("route") != "security_review":
            v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
            v["route"] = "human_review"
            v["verdict_action"] = "quarantine"
            v["escalation"] = "human_review"
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["qr_url_not_allowlisted"]))
    # Enforce auth-verdict gate: when sender policy is quarantine/reject and alignment fails, force security review.
    if (dmarc_result in ("fail", "reject", "quarantine") or dmarc_fail) and dmarc_policy in ("reject", "p=reject", "quarantine", "p=quarantine"):
        v["severity"] = "error"
        v["route"] = "security_review"
        v["verdict_action"] = "security_review"
        v["escalation"] = "security_middleware"
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["auth_alignment_failed_under_dmarc_policy"]))

    auth_pass_trusted_preferred = False
    # Prefer allow when auth passes and sender is trusted (unless critical signals present).
    try:
        auth_all_pass = (spf_result == "pass" and dkim_result == "pass" and (dmarc_result in ("pass", "", None)) and not bool(dmarc_fail))
        external_sender = bool(email.get("external_sender", False))
        from_domain = str((extracted.get("meta") or {}).get("from_domain") or "")
        trusted_domains = set([str(x).lower() for x in ((ff.get("SECURITY_THRESHOLDS") or {}).get("TRUSTED_SENDER_DOMAINS", []))])
        ind_types_set = {str((x or {}).get("type") or "") for x in (v.get("indicators") or [])}
        reason_types_set = {str(x or "") for x in (v.get("reasons") or [])}
        critical = {
            "dangerous_tool_intent",
            "prompt_injection",
            "lolbin_command",
            "c2_beacon_pattern",
            "data_exfil_intent",
            "yara_high_confidence_match",
            "yara_rule_match_detected",
        }
        if auth_all_pass and ((from_domain.lower() in trusted_domains) or (external_sender is False)):
            if not ((ind_types_set & critical) or (reason_types_set & critical)) and v.get("route") in ("human_review", None, "auto_resolve", "security_review"):
                auth_pass_trusted_preferred = True
                v["severity"] = "info"
                v["route"] = "auto_resolve"
                v["verdict_action"] = "allow"
                v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["auth_pass_trusted_sender_allow"]))
    except Exception:
        pass
    v.setdefault("evidence_snapshot", {})
    if isinstance(v.get("evidence_snapshot"), dict):
        v["evidence_snapshot"]["auth_verdicts"] = {
            "spf_result": spf_result or None,
            "dkim_result": dkim_result or None,
            "dmarc_result": dmarc_result or None,
            "dmarc_policy": dmarc_policy or None,
            "dmarc_fail": bool(dmarc_fail),
        }
        v["evidence_snapshot"]["ioc_quality"] = ioc_quality
        v["evidence_snapshot"]["header_forensics"] = header_forensics or {}
        v["evidence_snapshot"]["sender_infrastructure"] = _sender_infrastructure_snapshot(
            email,
            header_forensics if isinstance(header_forensics, dict) else {},
        )
        v["evidence_snapshot"]["mailbox_compromise"] = mailbox_compromise or {}
        v["evidence_snapshot"]["yara"] = {
            "engine": (yara_scan or {}).get("engine"),
            "rules_loaded": int((yara_scan or {}).get("rules_loaded") or 0),
            "match_count": int((yara_scan or {}).get("match_count") or 0),
            "matches": list((yara_scan or {}).get("matches") or []),
        }
        v["evidence_snapshot"]["semantic_bec"] = semantic_bec
        v["evidence_snapshot"]["thread_graph"] = thread_graph
        v["evidence_snapshot"]["ransomware_artifact"] = ransomware_artifact
        v["evidence_snapshot"]["coverage_limits"] = (ransomware_artifact or {}).get("coverage_limits") or ransomware_coverage_limits()
        v["evidence_snapshot"]["bimi_verification"] = ((extracted.get("meta") or {}).get("bimi_verification") if isinstance(extracted, dict) else {}) or {}
        v["evidence_snapshot"]["bimi_visual_similarity"] = ((extracted.get("meta") or {}).get("bimi_visual_similarity") if isinstance(extracted, dict) else {}) or {}
        try:
            v["evidence_snapshot"]["artifact_intel"] = {
                "parsed_fields": (artifact_intel.get("parsed_fields") if isinstance(artifact_intel, dict) else {}) or {},
                "baseline_checks": (artifact_intel.get("baseline_checks") if isinstance(artifact_intel, dict) else {}) or {},
                "forensics_details": (artifact_intel.get("forensics_details") if isinstance(artifact_intel, dict) else {}) or {},
                "signal_scores": (artifact_intel.get("signal_scores") if isinstance(artifact_intel, dict) else {}) or {},
            }
            v["evidence_snapshot"]["attachment_forensics"] = _attachment_forensics_snapshot(
                email,
                artifact_intel if isinstance(artifact_intel, dict) else {},
            )
            v["evidence_snapshot"]["attachment_baseline_diffs"] = _attachment_baseline_diff_snapshot(email)
            v["evidence_snapshot"]["attachment_visual_diffs"] = _attachment_visual_diff_snapshot(email)
        except Exception:
            pass
        v["evidence_snapshot"]["intake_gate"] = intake_meta
        v["evidence_snapshot"]["attachment_ingest_gate"] = ingest_gate_meta
        v["evidence_snapshot"]["ocr_qr_sanitization"] = ocr_sanitization_meta
        v["evidence_snapshot"]["content_classification"] = content_classification
    try:
        sig = ((artifact_intel or {}).get("signal_scores") or {})
        band = str(sig.get("band") or "auto-allow")
        if band == "block" and v.get("route") != "security_review":
            v["severity"] = "error"
            v["route"] = "security_review"
            v["verdict_action"] = "security_review"
            v["escalation"] = "security_middleware"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["artifact_risk_block_band"]))
        elif band == "review" and v.get("route") == "auto_resolve":
            v["severity"] = "warning"
            v["route"] = "human_review"
            v["verdict_action"] = "quarantine"
            v["escalation"] = "human_review"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["artifact_risk_review_band"]))
    except Exception:
        pass
    # Threat enrichment: MITRE, DREAD, CVSS, KEV, kill-chain stage
    sig_types = [str((x or {}).get("type") or "") for x in (v.get("indicators") or [])]
    ctx = "prompt_injection" if ("prompt_injection" in sig_types or "dangerous_tool_intent" in sig_types) else ("lolbin" if "lolbin_command" in sig_types else "prompt_injection")
    stage = infer_kill_chain_stage(event_type="email_security", signals=sig_types)
    threat = enrich_context(ctx, signals=sig_types + (["denylisted_ioc"] if int((v.get("evidence_snapshot") or {}).get("ioc_counts", {}).get("denylisted", 0)) > 0 else []), kill_chain_stage=stage)
    v["threat_correlation"] = threat
    if isinstance(v.get("evidence_snapshot"), dict):
        v["evidence_snapshot"]["kill_chain_stage"] = threat.get("kill_chain_stage")
        v["evidence_snapshot"]["threat_correlation"] = threat
    load_shed = _spoof_flood_load_shed_state(ff, tenant_id, v.get("indicators") or [])
    if isinstance(v.get("evidence_snapshot"), dict):
        v["evidence_snapshot"]["load_shed"] = load_shed
    if bool(load_shed.get("active")):
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["spoof_flood_load_shed_active"]))
    elif bool(load_shed.get("fast_path_only")):
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["spoof_flood_fast_path_only"]))
    if bool(load_shed.get("active") or load_shed.get("fast_path_only")):
        try:
            telemetry_emit(
                {
                    "type": "email_security",
                    "subtype": "spoof_flood_load_shed",
                    "tenant_id": tenant_id,
                    "load_shed": load_shed,
                },
                severity="warning",
                sourcetype="shopsquire:security",
            )
        except (TypeError, ValueError, RuntimeError) as exc:
            _record_runtime_error(
                runtime_errors,
                stage="load_shed.telemetry_emit",
                exc=exc,
                details={"tenant_id": tenant_id, "load_shed_active": bool(load_shed.get("active"))},
            )
    # P1 enrichment and safe detonation (best-effort, non-blocking) with flood load-shed.
    enrichment_error = None
    detonation_error = None
    if bool(load_shed.get("active") or load_shed.get("fast_path_only")):
        now = time.perf_counter()
        enrichment_t0 = now
        enrichment_t1 = now
        detonation_t0 = now
        detonation_t1 = now
        mode = "active" if bool(load_shed.get("active")) else "fast_path_only"
        enrichment = {"items": [], "malicious_hits": 0, "provider": "load_shed", "skipped": True, "mode": mode}
        detonation = {"provider": "load_shed", "malicious": False, "score": 0.0, "findings": [], "skipped": True, "mode": mode}
    else:
        enrichment_t0 = time.perf_counter()
        try:
            try:
                enrichment = enrich_iocs(v.get("iocs") or [], tenant_id=tenant_id)
            except TypeError:
                enrichment = enrich_iocs(v.get("iocs") or [])
        except Exception as e:
            enrichment = {"items": [], "malicious_hits": 0}
            enrichment_error = str(e)
        enrichment_t1 = time.perf_counter()
        try:
            from src.app.observability.metrics import record_email_enrichment_latency

            record_email_enrichment_latency("local_cache", max(0.0, enrichment_t1 - enrichment_t0))
        except (TypeError, ValueError, RuntimeError) as exc:
            _record_runtime_error(runtime_errors, stage="metrics.record_email_enrichment_latency", exc=exc)
        detonation_t0 = time.perf_counter()
        try:
            urls = [str(x.get("value") or "") for x in (v.get("iocs") or []) if str(x.get("type") or "") == "url" and x.get("value")]
            attachment_hashes = [str(a.get("sha256") or "") for a in (email.get("attachments") or []) if a.get("sha256")]
            detonation = detonate_targets(urls, attachment_hashes)
        except Exception as e:
            detonation = {"provider": "none", "malicious": False, "score": 0.0, "findings": []}
            detonation_error = str(e)
        detonation_t1 = time.perf_counter()
        try:
            from src.app.observability.metrics import record_email_detonation_latency

            record_email_detonation_latency(str(detonation.get("provider") or "none"), max(0.0, detonation_t1 - detonation_t0))
        except (TypeError, ValueError, RuntimeError) as exc:
            _record_runtime_error(runtime_errors, stage="metrics.record_email_detonation_latency", exc=exc)
    try:
        v["enrichment"] = enrichment
        v["detonation"] = detonation
        v["latency"] = {
            "enrichment_seconds": max(0.0, enrichment_t1 - enrichment_t0),
            "detonation_seconds": max(0.0, detonation_t1 - detonation_t0),
        }
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["latency"] = v["latency"]
            if enrichment_error:
                v["evidence_snapshot"]["enrichment_error"] = enrichment_error[:240]
            if detonation_error:
                v["evidence_snapshot"]["detonation_error"] = detonation_error[:240]
    except Exception:
        pass
    if enrichment_error:
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["ioc_enrichment_unavailable"]))
    if detonation_error:
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["sandbox_detonation_unavailable"]))
    # Enrichment may strengthen but never weaken deterministic rule-first decisions.
    try:
        if int(enrichment.get("malicious_hits") or 0) > 0 and v.get("route") != "security_review":
            v["severity"] = "error"
            v["verdict_action"] = "security_review"
            v["route"] = "security_review"
            v["escalation"] = "security_middleware"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["ioc_enrichment_malicious_hit"]))
        if bool(detonation.get("malicious")) and v.get("route") != "security_review":
            v["severity"] = "error"
            v["verdict_action"] = "security_review"
            v["route"] = "security_review"
            v["escalation"] = "security_middleware"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["sandbox_detonation_malicious"]))
    except Exception:
        pass
    try:
        v["sender_trust"] = trust
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["sender_trust"] = trust
    except (TypeError, ValueError, RuntimeError) as exc:
        _record_runtime_error(runtime_errors, stage="enrichment.assign_results", exc=exc)
    phishing_page_stage = {}
    try:
        urls = [str(x.get("value") or "") for x in (v.get("iocs") or []) if str(x.get("type") or "") == "url" and x.get("value")]
        phishing_page_stage = analyze_phishing_targets(urls, enrichment=enrichment, detonation=detonation, tenant_id=tenant_id)
        p_inds = list((phishing_page_stage or {}).get("indicators") or [])
        if p_inds:
            v["indicators"] = list(v.get("indicators") or []) + p_inds
            max_prisk = float((phishing_page_stage or {}).get("max_risk_score") or 0.0)
            if max_prisk >= 0.85:
                v["severity"] = "error"
                v["route"] = "security_review"
                v["verdict_action"] = "security_review"
                v["escalation"] = "security_middleware"
                v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["phishing_landing_page_high_risk"]))
            elif v.get("route") == "auto_resolve":
                v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
                v["route"] = "human_review"
                v["verdict_action"] = "quarantine"
                v["escalation"] = "human_review"
                v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["phishing_landing_page_review"]))
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["phishing_page_stage"] = phishing_page_stage or {}
    except (TypeError, ValueError, RuntimeError) as exc:
        _record_runtime_error(runtime_errors, stage="phishing_page_stage", exc=exc)
        phishing_page_stage = {}

    # Trust-score fusion: sender trust + IOC + sandbox + ingest controls -> progressive access policy.
    trust_case = None
    access_policy = None
    sandbox_ioc = _sandbox_ioc_stage(enrichment, detonation, ioc_quality)
    try:
        auth_failed = bool(
            dmarc_fail
            or dmarc_result in ("fail", "quarantine", "reject")
            or (spf_result in ("fail", "softfail") and dkim_result in ("fail", "neutral", ""))
        )
        base_sender_trust = float((trust or {}).get("sender_trust_score") or 0.5)
        trust_case_dec = fuse_security_trust_score(
            base_trust_score=base_sender_trust,
            sender_trust=trust if isinstance(trust, dict) else {},
            ioc_malicious_hits=int((enrichment or {}).get("malicious_hits") or 0),
            detonation=detonation if isinstance(detonation, dict) else {},
            ingest_blocked=bool((ingest_gate_meta or {}).get("blocked")) or int((ocr_sanitization_meta or {}).get("blocked_qr_url_count") or 0) > 0,
            auth_failed=auth_failed,
            load_shed_active=bool((load_shed or {}).get("active")),
        )
        trust_case = {
            "score": float(trust_case_dec.trust_score),
            "raw_score": float(trust_case_dec.raw_trust_score),
            "calibrated_score": float(trust_case_dec.calibrated_trust_score),
            "calibration_source": str(trust_case_dec.calibration_source),
            "level": trust_case_dec.trust_level,
            "progressive_access": trust_case_dec.progressive_access,
            "forced_reauth": bool(trust_case_dec.forced_reauth),
            "actions": trust_case_dec.actions,
            "reasons": trust_case_dec.reasons,
            "factors": trust_case_dec.factors,
        }
        access_policy = {
            "progressive_access": trust_case_dec.progressive_access,
            "forced_reauth": bool(trust_case_dec.forced_reauth),
            "actions": trust_case_dec.actions,
            "decision_source": "trust_score_fusion_v1",
        }
        v["trust_case"] = trust_case
        v["access_policy"] = access_policy
        v["policy_actions"] = trust_case_dec.actions
        if bool(trust_case_dec.forced_reauth):
            v["severity"] = "error"
            v["route"] = "security_review"
            v["verdict_action"] = "security_review"
            v["escalation"] = "security_middleware"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["forced_reauth_required"]))
        elif trust_case_dec.progressive_access in ("restricted", "challenge") and v.get("route") == "auto_resolve" and not auth_pass_trusted_preferred:
            v["severity"] = "warning" if v.get("severity") == "info" else v.get("severity")
            v["route"] = "human_review"
            v["verdict_action"] = "quarantine"
            v["escalation"] = "human_review"
            v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + [f"progressive_access_{trust_case_dec.progressive_access}"]))
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["sandbox_ioc_stage"] = sandbox_ioc
            v["evidence_snapshot"]["trust_case"] = trust_case
            v["evidence_snapshot"]["access_policy"] = access_policy
    except Exception:
        trust_case = None
        access_policy = None

    # P1 LLM assist: summary/secondary signal only (non-authoritative).
    llm_assist = _llm_assist_summary(email, extracted, v, ff=ff)
    llm_controls = _llm_control_policy(extracted, ff=ff)
    if llm_controls.get("policy_gate") == "deny":
        v["severity"] = "error"
        v["verdict_action"] = "security_review"
        v["route"] = "security_review"
        v["escalation"] = "security_middleware"
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["llm_policy_gate_denied"]))

    _apply_reference_material_suppression(
        v,
        email=email,
        extracted=extracted,
        content_classification=content_classification,
        dmarc_fail=bool(dmarc_fail),
        enrichment=enrichment if isinstance(enrichment, dict) else {},
        detonation=detonation if isinstance(detonation, dict) else {},
    )

    # Map severity to risk band for playbook selection
    risk_band = {
        "info": "low",
        "warning": "medium",
        "error": "high",
    }.get(v["severity"], "low")

    # Select a CV playbook based on tags and risk band
    pb_sel = select_cv_playbook(v.get("tags") or [], risk_band)
    pb_info = pb_sel.get("playbook") if isinstance(pb_sel, dict) else None
    try:
        v["risk_band"] = risk_band
        v["playbook"] = pb_info
        v["content_mode"] = content_classification.get("mode")
        v["content_classification"] = content_classification
        v["llm_controls"] = llm_controls
        v["llm_assist"] = llm_assist
        v["applied_thresholds"] = {
            "sender_trust_low_threshold": float(
                rt_thr.get("sender_trust_low_threshold", (thr or {}).get("SENDER_TRUST_LOW_THRESHOLD", 0.35))
            ),
            "ioc_fusion_malicious_threshold": float(rt_thr.get("ioc_fusion_malicious_threshold", 0.7)),
            "spoof_flood_per_min": int((load_shed or {}).get("per_min") or 0),
            "spoof_flood_load_shed_active": bool((load_shed or {}).get("active")),
            "force_reauth_below": float(((ff.get("TRUST_THRESHOLDS") or {}).get("force_reauth_below", 0.35)) if isinstance(ff, dict) else 0.35),
        }
        v["policy_gate"] = {
            "decision": "deny" if (v.get("route") == "security_review") else ("review" if v.get("route") == "human_review" else "allow"),
            "reason": "rule_first_gate",
        }
        # P2 fuzzy/canary summary for downstream clustering and validation.
        simhash = None
        canary_triggered = False
        for ind in (v.get("indicators") or []):
            if ind.get("type") == "simhash_fingerprint":
                simhash = ind.get("value")
            if ind.get("type") == "canary_token_triggered":
                canary_triggered = True
        v["fuzzy_signals"] = {
            "simhash": simhash,
            "phish_cluster_key": (_hash16(f"{extracted.get('meta', {}).get('from_domain') or 'na'}:{simhash or 'na'}") or str(simhash or "na")),
            "canary_triggered": bool(canary_triggered),
        }
        if isinstance(pb_info, dict) and pb_info.get("id"):
            v["playbook_run"] = {
                "status": "selected",
                "run_id": None,
                "playbook_id": pb_info.get("id"),
                "title": pb_info.get("title"),
                "lane": None,
            }
    except Exception:
        pass
    try:
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["intake_gate"] = intake_meta
            v["evidence_snapshot"]["attachment_ingest_gate"] = ingest_gate_meta
            v["evidence_snapshot"]["ocr_qr_sanitization"] = ocr_sanitization_meta
            v["evidence_snapshot"]["content_classification"] = content_classification
    except Exception:
        pass
    try:
        bec_kill_chain = infer_bec_kill_chain(email, v)
    except Exception:
        bec_kill_chain = {"stage": "Reconnaissance", "stages": ["Reconnaissance"], "attack_flow": ["Reconnaissance"], "confidence": 0.3, "signal_count": 0}
    try:
        v["bec_kill_chain"] = bec_kill_chain
        v["bec_kill_chain_stage"] = bec_kill_chain.get("stage")
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["bec_kill_chain"] = bec_kill_chain
    except Exception:
        pass
    try:
        if isinstance(v.get("evidence_snapshot"), dict):
            evs = v["evidence_snapshot"]
            evs["findings_schema_version"] = "email_security_findings.v1"
            evs["agent_boundaries"] = _email_agent_boundaries()
            evs["pre_agent_gate"] = _build_pre_agent_gate_snapshot(
                ingest_gate_meta=ingest_gate_meta if isinstance(ingest_gate_meta, dict) else {},
                ocr_sanitization_meta=ocr_sanitization_meta if isinstance(ocr_sanitization_meta, dict) else {},
                llm_controls=llm_controls if isinstance(llm_controls, dict) else {},
            )
            structured_findings = _build_structured_findings(
                email=email,
                verdict=v,
                evidence_snapshot=evs,
                suggested_baseline_version="current",
            )
            structured_findings = _decorate_structured_findings(
                findings=structured_findings,
                evidence_snapshot=evs,
            )
            top_ranked_findings = _dedupe_ranked_findings(structured_findings, limit=3)
            evs["structured_findings"] = structured_findings
            evs["top_ranked_findings"] = top_ranked_findings
            evs["finding_groups"] = {
                "active_findings": [f for f in structured_findings if isinstance(f, dict) and str(f.get("finding_group") or "") == "active_findings" and str(f.get("claim_status") or "") in {"observed", "inferred"}][:8],
                "detection_artifact_patterns": [f for f in structured_findings if isinstance(f, dict) and str(f.get("finding_group") or "") == "detection_artifact_patterns"][:8],
                "unconfirmed_higher_order_hypotheses": [f for f in structured_findings if isinstance(f, dict) and str(f.get("finding_group") or "") == "unconfirmed_higher_order_hypotheses"][:8],
            }
            supplier_governance = update_supplier_governance_snapshot(
                tenant_id=tenant_id,
                email=email,
                evidence_snapshot=evs,
                structured_findings=structured_findings,
            )
            evs["supplier_governance"] = supplier_governance
            incident_graph = build_incident_graph_snapshot(
                tenant_id=tenant_id,
                supplier_key=str((supplier_governance or {}).get("supplier_key") or ""),
                evidence_snapshot=evs,
            )
            action_policy = _build_action_policy(
                verdict=v,
                structured_findings=structured_findings,
                evidence_snapshot=evs,
            )
            # Surface VBA/macro execution findings as a human-readable reason so
            # they appear in the top-level "reasons" field.  macro_auto_execution_lure
            # findings come from the passive-payload classifier for .bas/.xlsm files
            # with uncommented auto-execution subs (Sub Auto_Open, Sub Workbook_Open).
            try:
                _macro_ftypes = {"macro_auto_execution_lure", "lolbin_command_sequence"}
                if any(
                    str((f or {}).get("finding_type") or "") in _macro_ftypes
                    for f in (structured_findings or [])
                    if isinstance(f, dict)
                ):
                    v["reasons"] = list(dict.fromkeys(
                        (v.get("reasons") or []) + ["vba_macro_execution_indicator_detected"]
                    ))
            except Exception:
                pass
            vendor_trust_graph = build_vendor_trust_graph_snapshot(
                governance_snapshot=supplier_governance,
                evidence_snapshot=evs,
                structured_findings=structured_findings,
            )
            if isinstance(vendor_trust_graph, dict):
                vendor_trust_graph["incident_count"] = int((incident_graph or {}).get("incident_count") or 0)
                vendor_trust_graph["timeline"] = list((incident_graph or {}).get("timeline") or [])[:6]
                vendor_trust_graph["related_incident_ids"] = list((incident_graph or {}).get("related_incident_ids") or [])[:8]
            evs["action_policy"] = action_policy
            evs["human_gate"] = dict(action_policy.get("human_gate") or {})
            evs["incident_graph"] = incident_graph
            evs["vendor_trust_graph"] = vendor_trust_graph
            evs["threat_hunter_leads"] = build_threat_hunter_leads(
                findings=structured_findings,
                evidence_snapshot=evs,
                llm_assist=llm_assist if isinstance(llm_assist, dict) else {},
            )
            evs["agent_runs"] = _build_agent_runs_audit(
                evidence_snapshot=evs,
                structured_findings=structured_findings,
                policy_gate=v.get("policy_gate") if isinstance(v.get("policy_gate"), dict) else {},
            )
            if isinstance(security_analysis, dict):
                security_analysis["agent_invocations"] = list(evs.get("agent_runs") or [])[:8]
                if isinstance(ocr_sanitization_meta, dict):
                    security_analysis["ocr_confidence"] = ocr_sanitization_meta.get("ocr_confidence")
                    security_analysis["ocr_engine"] = ocr_sanitization_meta.get("ocr_engine")
                    security_analysis["ocr_word_count"] = ocr_sanitization_meta.get("ocr_word_count")
            v["action_policy"] = action_policy
            v["human_gate"] = dict(action_policy.get("human_gate") or {})
            v["threat_hunter_leads"] = list(evs.get("threat_hunter_leads") or [])
    except Exception:
        pass
    try:
        explainability_card = _build_explainability_card(
            verdict=v,
            extracted=extracted,
            artifact_intel=artifact_intel if isinstance(artifact_intel, dict) else {},
            ioc_quality=ioc_quality if isinstance(ioc_quality, dict) else {},
            semantic_bec=semantic_bec if isinstance(semantic_bec, dict) else {},
            yara_scan=yara_scan if isinstance(yara_scan, dict) else {},
            ransomware_artifact=ransomware_artifact if isinstance(ransomware_artifact, dict) else {},
            dmarc_fail=bool(dmarc_fail),
        )
        if isinstance(v.get("evidence_snapshot"), dict):
            explainability_card["top_ranked_findings"] = list((v["evidence_snapshot"].get("top_ranked_findings") or [])[:3])
            explainability_card["pre_agent_gate"] = dict(v["evidence_snapshot"].get("pre_agent_gate") or {})
            explainability_card["agent_runs"] = list((v["evidence_snapshot"].get("agent_runs") or [])[:6])
            explainability_card["action_policy"] = dict(v["evidence_snapshot"].get("action_policy") or {})
            explainability_card["human_gate"] = dict(v["evidence_snapshot"].get("human_gate") or {})
            explainability_card["threat_hunter_leads"] = list((v["evidence_snapshot"].get("threat_hunter_leads") or [])[:4])
        v["explainability_card"] = explainability_card
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["explainability_card"] = explainability_card
    except Exception:
        pass
    # Metrics: verdict
    try:
        from src.app.observability.metrics import record_email_security_verdict

        record_email_security_verdict(tenant_id, v["severity"])
    except Exception:
        pass
    try:
        from src.app.observability.metrics import record_email_security_route

        record_email_security_route(tenant_id, v.get("route"), v.get("escalation"))
    except Exception:
        pass

    evt = {
        "type": "email_security",
        "subtype": "bec_verdict",
        "tenant_id": tenant_id,
        "severity": v["severity"],
        "verdict_action": v.get("verdict_action"),
        "route": v.get("route"),
        "escalation": v.get("escalation"),
        "reasons": v["reasons"],
        "evidence": v["evidence_snapshot"],
        "indicator_count": len(v.get("indicators") or []),
        "ioc_counts": v["evidence_snapshot"].get("ioc_counts"),
        "tags": v.get("tags") or ["email_security"],
        "playbook_id": (pb_info or {}).get("id"),
        "playbook_title": (pb_info or {}).get("title"),
        "risk_band": risk_band,
        "llm_controls": llm_controls,
        "fuzzy_signals": v.get("fuzzy_signals"),
        "enrichment": v.get("enrichment"),
        "detonation": v.get("detonation"),
        "sandbox_ioc_stage": sandbox_ioc,
        "phishing_page_stage": phishing_page_stage,
        "llm_assist": llm_assist,
        "sender_trust": trust,
        "trust_case": trust_case,
        "access_policy": access_policy,
        "threat_correlation": threat,
        "mailbox_compromise": mailbox_compromise,
        "ransomware_artifact": ransomware_artifact,
        "bec_kill_chain": bec_kill_chain,
        "explainability_card": v.get("explainability_card"),
    }
    try:
        telemetry_emit(evt, severity=v["severity"], sourcetype="shopsquire:security")
    except Exception:
        pass

    # Ticket flood protection
    key = f"bec:{tenant_id or 'default'}"
    allowed, count = _within_rate_limit(key, per_min=per_min, enabled=enabled)
    ticket_created = False
    ticket_rate_limited = False
    ticket_deduped = False
    ticket_id: str | None = None
    if v["severity"] in ("warning", "error") or v.get("route") in ("human_review", "security_review"):
        if allowed:
            dedupe_ok = _dedupe_ok(str(email.get("message_id") or ""), tenant_id)
            if not dedupe_ok:
                ticket_deduped = True
                try:
                    from src.app.observability.metrics import record_email_security_dedupe_drop

                    record_email_security_dedupe_drop(tenant_id)
                except Exception:
                    pass
            if dedupe_ok:
                try:
                    t = TicketingAgent().create_ticket(
                        title=f"Email security {v['severity'].upper()}" + (f" · {evt.get('playbook_title')}" if evt.get('playbook_title') else ""),
                        description=f"Reasons: {', '.join(v['reasons'])}" + (f"; Playbook: {evt.get('playbook_id')}" if evt.get('playbook_id') else ""),
                        severity=("high" if v.get("route") == "security_review" or v["severity"] == "error" else "medium"),
                        tenant_id=tenant_id or "default",
                        reason_code="email_bec_verdict",
                        cv_summary=evt,
                        approval_required=False,
                    )
                    try:
                        ticket_id = getattr(t, "id", None)
                    except Exception:
                        ticket_id = None
                    ticket_created = True
                    try:
                        from src.app.observability.metrics import record_email_security_ticket

                        record_email_security_ticket(tenant_id, v["severity"])
                    except (TypeError, ValueError, RuntimeError) as exc:
                        _record_runtime_error(runtime_errors, stage="metrics.record_email_security_ticket", exc=exc)
                except (TypeError, ValueError, RuntimeError) as exc:
                    _record_runtime_error(runtime_errors, stage="ticket.create", exc=exc)
        else:
            # Emit aggregation telemetry but do not open ticket
            ticket_rate_limited = True
            try:
                telemetry_emit({"type": "email_security", "subtype": "ticket_rate_limited", "count": count, "tenant_id": tenant_id}, severity=v["severity"], sourcetype="shopsquire:security")
            except (TypeError, ValueError, RuntimeError) as exc:
                _record_runtime_error(runtime_errors, stage="telemetry.ticket_rate_limited", exc=exc)
            try:
                from src.app.observability.metrics import record_email_security_rate_limited

                record_email_security_rate_limited(tenant_id)
            except (TypeError, ValueError, RuntimeError) as exc:
                _record_runtime_error(runtime_errors, stage="metrics.record_email_security_rate_limited", exc=exc)

    # Bitemporal decision + trace events
    decision_id = None
    security_analysis: Dict[str, Any] | None = None
    try:
        # Correlate to frameworks for decision-trace drilldown (why it was flagged).
        # Keep deterministic and defensive-only; used for audit/reporting and UI panels.
        try:
            # Minimal signal map for downstream correlation; avoid leaking raw email.
            structured_signal_findings = [
                f
                for f in (((v.get("evidence_snapshot") or {}).get("structured_findings") or [])[:32])
                if isinstance(f, dict) and str(f.get("claim_status") or "").strip().lower() in {"observed", "inferred", "possible"}
            ]
            sig = {
                "dmarc_fail": bool(dmarc_fail),
                "prompt_injection": any(str(f.get("finding_type") or "") == "prompt_injection_hidden" for f in structured_signal_findings),
                "dangerous_tool_intent": any(str((i or {}).get("type") or "") == "dangerous_tool_intent" for i in (v.get("indicators") or [])),
                "data_exfiltration": any(str((i or {}).get("type") or "") in ("data_exfil_intent",) for i in (v.get("indicators") or []))
                or any(str(f.get("finding_type") or "") == "data_exfiltration_instruction" for f in structured_signal_findings),
                "email_c2_beaconing": any(str(f.get("finding_type") or "") == "c2_beacon_pattern" for f in structured_signal_findings),
                "unicode_confusable": any(str((i or {}).get("type") or "") in ("confusable_homoglyph_domain", "vendor_homoglyph_impersonation") for i in (v.get("indicators") or [])),
                "thread_hijack": bool(email.get("prior_reply_chain_id")) and bool(email.get("reply_chain_id")) and str(email.get("prior_reply_chain_id")) != str(email.get("reply_chain_id")),
                "thread_reentry_after_silence": bool(((v.get("evidence_snapshot") or {}).get("thread_graph") or {}).get("reentry_after_silence")),
                "thread_sender_domain_drift": bool(((v.get("evidence_snapshot") or {}).get("thread_graph") or {}).get("sender_domain_drift")),
                "semantic_bec_high_risk": float(((v.get("evidence_snapshot") or {}).get("semantic_bec") or {}).get("score") or 0.0) >= float(((v.get("evidence_snapshot") or {}).get("semantic_bec") or {}).get("security_threshold") or 0.82),
                "yara_match": int(((v.get("evidence_snapshot") or {}).get("yara") or {}).get("match_count") or 0) > 0,
                "yara_high_confidence": any(
                    float((m or {}).get("confidence") or 0.0) >= 0.85
                    for m in (((v.get("evidence_snapshot") or {}).get("yara") or {}).get("matches") or [])
                ),
                "ransomware_shadow_copy_command": any(
                    str((i or {}).get("type") or "") == "ransomware_shadow_copy_deletion_command"
                    for i in (v.get("indicators") or [])
                ),
                "ransomware_office_script_chain": any(
                    str((i or {}).get("type") or "") == "ransomware_office_to_script_chain_indicator"
                    for i in (v.get("indicators") or [])
                ),
                "ransomware_entropy_hint": any(
                    str((i or {}).get("type") or "") == "ransomware_attachment_entropy_hint"
                    for i in (v.get("indicators") or [])
                ),
                "ransomware_canary_targeting": any(
                    str((i or {}).get("type") or "") == "ransomware_canary_targeting_pattern"
                    for i in (v.get("indicators") or [])
                ),
            }
        except Exception as exc:
            _record_runtime_error(runtime_errors, stage="security_signal_map", exc=(exc if isinstance(exc, Exception) else RuntimeError(str(exc))))
            sig = {"dmarc_fail": bool(dmarc_fail)}
        security_analysis = correlate_security_analysis(
            channel="email",
            severity=str(v.get("severity") or ""),
            tags=list(v.get("tags") or []),
            reasons=list(v.get("reasons") or []),
            threat_correlation=(v.get("threat_correlation") or {}) if isinstance(v.get("threat_correlation"), dict) else None,
            signals=sig,
            evidence={
                "case_facts": {
                    "from_addr": email.get("from_addr"),
                    "reply_to": email.get("reply_to"),
                    "subject": email.get("subject"),
                    "route": v.get("route"),
                    "verdict_action": v.get("verdict_action"),
                },
                "top_ranked_findings": ((v.get("evidence_snapshot") or {}).get("top_ranked_findings") or [])[:5],
                "artifact_evidence": [
                    str(x.get("summary") or "")
                    for x in (((v.get("evidence_snapshot") or {}).get("top_ranked_findings") or [])[:5])
                    if isinstance(x, dict) and str(x.get("claim_status") or "").strip().lower() in {"observed", "inferred"}
                ][:6],
                "artifact_claims": [
                    {
                        "finding_id": str(x.get("finding_id") or ""),
                        "finding_type": str(x.get("finding_type") or ""),
                        "summary": str(x.get("summary") or ""),
                        "claim_status": str(x.get("claim_status") or ""),
                        "finding_group": str(x.get("finding_group") or ""),
                        "source_type": str(x.get("source_type") or ""),
                        "evidence_lane": str(x.get("evidence_lane") or ""),
                        "evidence_refs": list(x.get("evidence_refs") or []),
                        "evidence_summary": list(x.get("evidence") or [])[:4],
                        "mitre_attack": list(x.get("mitre_attack") or [])[:6],
                        "possible_mitre_attack": list(x.get("possible_mitre_attack") or [])[:6],
                        "mitre_atlas": list(x.get("mitre_atlas") or [])[:4],
                        "possible_mitre_atlas": list(x.get("possible_mitre_atlas") or [])[:4],
                        "pasta_stage": str(x.get("pasta_stage") or ""),
                        "business_outcome": str(x.get("business_outcome") or ""),
                        "runtime_confirmation_required": bool(x.get("runtime_confirmation_required")),
                        "runtime_evidence_required": list(x.get("runtime_evidence_required") or [])[:6],
                        "runtime_evidence_present": list(x.get("runtime_evidence_present") or [])[:6],
                        "artifact_provenance": list(x.get("artifact_provenance") or [])[:6],
                        "source_file": str((((x.get("artifact_provenance") or [{}])[0]) or {}).get("source_file") or ""),
                        "extraction_method": str((((x.get("artifact_provenance") or [{}])[0]) or {}).get("extraction_method") or ""),
                        "exact_match_ref": str((((x.get("artifact_provenance") or [{}])[0]) or {}).get("match_ref") or ""),
                        "confidence": str((((x.get("artifact_provenance") or [{}])[0]) or {}).get("confidence") or ""),
                        "ocr_confidence": x.get("ocr_confidence"),
                        "model_targeting_evidence": list(x.get("model_targeting_evidence") or [])[:6],
                    }
                    for x in (((v.get("evidence_snapshot") or {}).get("structured_findings") or [])[:16])
                    if isinstance(x, dict)
                ],
                "sender_infrastructure": {
                    "related_incident_count": int((((v.get("evidence_snapshot") or {}).get("sender_infrastructure") or {}).get("related_incidents") or {}).get("count") or 0),
                },
                "ioc_counts": (v.get("evidence_snapshot") or {}).get("ioc_counts"),
                "artifact_intel": (v.get("evidence_snapshot") or {}).get("artifact_intel"),
                "intake_gate": (v.get("evidence_snapshot") or {}).get("intake_gate"),
                "attachment_ingest_gate": (v.get("evidence_snapshot") or {}).get("attachment_ingest_gate"),
                "ocr_qr_sanitization": (v.get("evidence_snapshot") or {}).get("ocr_qr_sanitization"),
                "ocr_confidence": ((v.get("evidence_snapshot") or {}).get("ocr_qr_sanitization") or {}).get("ocr_confidence"),
                "ocr_engine": ((v.get("evidence_snapshot") or {}).get("ocr_qr_sanitization") or {}).get("ocr_engine"),
                "ocr_word_count": ((v.get("evidence_snapshot") or {}).get("ocr_qr_sanitization") or {}).get("ocr_word_count"),
                "trust_case": trust_case,
                "semantic_bec": (v.get("evidence_snapshot") or {}).get("semantic_bec"),
                "yara": (v.get("evidence_snapshot") or {}).get("yara"),
                "thread_graph": (v.get("evidence_snapshot") or {}).get("thread_graph"),
                "ransomware_artifact": (v.get("evidence_snapshot") or {}).get("ransomware_artifact"),
                "coverage_limits": (v.get("evidence_snapshot") or {}).get("coverage_limits"),
            },
        )
    except Exception as exc:
        _record_runtime_error(runtime_errors, stage="security_framework_correlation", exc=(exc if isinstance(exc, Exception) else RuntimeError(str(exc))))
        security_analysis = None
    try:
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["security_analysis"] = security_analysis or {}
    except Exception:
        pass

    try:
        decision_id = log_decision(
            agent_name="email_security_agent",
            tenant_id=tenant_id,
            input_data={
                "message_id": email.get("message_id"),
                "from_addr": email.get("from_addr"),
                "reply_to": email.get("reply_to"),
                "subject": email.get("subject"),
                "dmarc_fail": dmarc_fail,
            },
            retrieved_context={
                "indicators": v.get("indicators"),
                "iocs": v.get("iocs"),
                "meta": extracted.get("meta"),
                "llm_controls": llm_controls,
                "fuzzy_signals": v.get("fuzzy_signals"),
                "ticket_id": ticket_id,
                "security_analysis": security_analysis,
                "attachment_ingest_gate": ingest_gate_meta,
                "ocr_qr_sanitization": ocr_sanitization_meta,
                "sandbox_ioc_stage": sandbox_ioc,
                "trust_case": trust_case,
                "mailbox_compromise": mailbox_compromise,
                "phishing_page_stage": phishing_page_stage,
                "bec_kill_chain": bec_kill_chain,
            },
            proposed_action={
                "severity": v.get("severity"),
                "verdict_action": v.get("verdict_action"),
                "route": v.get("route"),
                "escalation": v.get("escalation"),
                "policy_gate": v.get("policy_gate"),
                "risk_band": v.get("risk_band"),
                "access_policy": access_policy,
                "reasons": v.get("reasons"),
            },
            agent_reasoning="rule_first_email_security",
            policy_version="email_security_v1",
            approval_required=bool(v.get("route") in ("human_review", "security_review")),
            execution_status="review_required" if v.get("route") in ("human_review", "security_review") else "approved",
            event_type="email_security_verdict",
        )
    except Exception as exc:
        _record_runtime_error(runtime_errors, stage="decision_log.persist", exc=(exc if isinstance(exc, Exception) else RuntimeError(str(exc))))
        decision_id = None
    try:
        if decision_id:
            log_trace_event(
                trace_id=decision_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Email_Security_Agent",
                target_type="email",
                target_id=_hash16(str(email.get("message_id") or "")),
                payload={
                    "severity": v.get("severity"),
                    "verdict_action": v.get("verdict_action"),
                    "route": v.get("route"),
                    "escalation": v.get("escalation"),
                    "kill_chain_stage": (v.get("threat_correlation") or {}).get("kill_chain_stage"),
                    "mitre_attack": (v.get("threat_correlation") or {}).get("mitre_attack"),
                    "dread": (v.get("threat_correlation") or {}).get("dread"),
                    "cvss": (v.get("threat_correlation") or {}).get("cvss"),
                    "kev": (v.get("threat_correlation") or {}).get("kev"),
                    "frameworks": security_analysis,
                    "ioc_counts": (v.get("evidence_snapshot") or {}).get("ioc_counts"),
                    "tags": v.get("tags"),
                    "detonation": v.get("detonation"),
                    "enrichment": v.get("enrichment"),
                    "sender_trust": trust,
                    "artifact_intel": (v.get("evidence_snapshot") or {}).get("artifact_intel"),
                    "load_shed": load_shed,
                    "attachment_ingest_gate": ingest_gate_meta,
                    "ocr_qr_sanitization": ocr_sanitization_meta,
                    "sandbox_ioc_stage": sandbox_ioc,
                    "trust_case": trust_case,
                    "access_policy": access_policy,
                    "mailbox_compromise": mailbox_compromise,
                    "phishing_page_stage": phishing_page_stage,
                    "bec_kill_chain": bec_kill_chain,
                    "autonomy_governance": email.get("autonomy_governance") or {},
                },
            )
            log_trace_event(
                trace_id=decision_id,
                event_type="autonomy_governance",
                source_type="policy",
                source_id="Email_Autonomy_Governance_Agent",
                target_type="system",
                target_id=None,
                payload=email.get("autonomy_governance") or {},
            )
            log_trace_event(
                trace_id=decision_id,
                event_type="sender_trust_assessed",
                source_type="agent",
                source_id="Email_Trust_Graph_Agent",
                target_type="sender",
                target_id=(v.get("evidence_snapshot") or {}).get("from_domain_hash"),
                payload=trust or {},
            )
            log_trace_event(
                trace_id=decision_id,
                event_type="ioc_enrichment_fusion",
                source_type="agent",
                source_id="IOC_Enrichment_Agent",
                target_type="ioc",
                target_id=None,
                payload={
                    "malicious_hits": int((v.get("enrichment") or {}).get("malicious_hits") or 0),
                    "cache_hits": int((v.get("enrichment") or {}).get("cache_hits") or 0),
                    "contradictions": int((v.get("enrichment") or {}).get("contradictions") or 0),
                    "provider_weights": (v.get("enrichment") or {}).get("provider_weights") or {},
                },
            )
            log_trace_event(
                trace_id=decision_id,
                event_type="policy_gate",
                source_type="agent",
                source_id="Email_Policy_Gate_Agent",
                target_type="system",
                target_id=None,
                payload=v.get("policy_gate") or {},
            )
            log_trace_event(
                trace_id=decision_id,
                event_type="trust_policy",
                source_type="agent",
                source_id="Trust_Policy_Agent",
                target_type="identity",
                target_id=(v.get("evidence_snapshot") or {}).get("from_domain_hash"),
                payload={
                    "trust_case": trust_case or {},
                    "access_policy": access_policy or {},
                    "sandbox_ioc_stage": sandbox_ioc or {},
                    "mailbox_compromise": mailbox_compromise or {},
                    "phishing_page_stage": phishing_page_stage or {},
                },
            )
            if v.get("fuzzy_signals", {}).get("canary_triggered"):
                log_trace_event(
                    trace_id=decision_id,
                    event_type="canary_triggered",
                    source_type="agent",
                    source_id="Email_Canary_Agent",
                    target_type="security",
                    target_id=None,
                    payload=v.get("fuzzy_signals") or {},
                )
            log_trace_event(
                trace_id=decision_id,
                event_type="kill_chain_stage",
                source_type="agent",
                source_id="Threat_Correlation_Agent",
                target_type="security",
                target_id=None,
                payload=v.get("threat_correlation") or {},
            )
            log_trace_event(
                trace_id=decision_id,
                event_type="bec_kill_chain",
                source_type="agent",
                source_id="BEC_KillChain_Agent",
                target_type="security",
                target_id=None,
                payload=bec_kill_chain or {},
            )
            if v.get("route") == "security_review":
                log_trace_event(
                    trace_id=decision_id,
                    event_type="security_review_started",
                    source_type="agent",
                    source_id="Email_Routing_Agent",
                    target_type="security",
                    target_id=None,
                    payload={"ticket_id": ticket_id, "escalation": v.get("escalation")},
                )
            elif v.get("route") == "human_review":
                log_trace_event(
                    trace_id=decision_id,
                    event_type="human_override_requested",
                    source_type="agent",
                    source_id="Email_Routing_Agent",
                    target_type="human",
                    target_id=None,
                    payload={"ticket_id": ticket_id, "reason": v.get("reasons")},
                )
    except Exception as exc:
        _record_runtime_error(runtime_errors, stage="trace.emit_core", exc=(exc if isinstance(exc, Exception) else RuntimeError(str(exc))))

    if decision_id and runtime_errors:
        for err in runtime_errors[:12]:
            try:
                log_trace_event(
                    trace_id=decision_id,
                    event_type="system_error",
                    source_type="system",
                    source_id="Email_Security_Agent",
                    target_type="system",
                    target_id=None,
                    payload=err,
                )
            except Exception:
                pass

    v["decision_id"] = decision_id
    v["decision_trace_id"] = decision_id
    try:
        if decision_id and isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["trace_id"] = decision_id
            for row in (v["evidence_snapshot"].get("agent_runs") or []):
                if isinstance(row, dict):
                    row["trace_id"] = decision_id
            if isinstance(v.get("explainability_card"), dict):
                v["explainability_card"]["trace_id"] = decision_id
                v["explainability_card"]["agent_runs"] = list((v["evidence_snapshot"].get("agent_runs") or [])[:6])
                v["evidence_snapshot"]["explainability_card"] = v["explainability_card"]
    except Exception:
        pass
    if runtime_errors:
        v["runtime_errors"] = runtime_errors[:20]

    # Playbook-driven response (best-effort): start a run and execute typed automatic actions.
    # Manual approval actions are skipped by execute_typed_actions() and land in "skipped".
    try:
        autorun = str(os.getenv("PLAYBOOK_AUTORUN_ENABLED", "1")).strip().lower() in ("1", "true", "yes")
    except Exception:
        autorun = True
    try:
        if autorun and decision_id and isinstance(pb_info, dict) and pb_info.get("id"):
            action_policy = v.get("action_policy") if isinstance(v.get("action_policy"), dict) else {}
            run_id = start_playbook_run(
                trace_id=decision_id,
                decision_id=decision_id,
                tenant_id=tenant_id,
                playbook=pb_info,
                owner="Email_Security_Agent",
                metadata={"tags": v.get("tags") or [], "severity": v.get("severity"), "route": v.get("route")},
            )
            if run_id:
                append_playbook_step(run_id=run_id, event_type="selected", status="completed", evidence={"playbook_id": pb_info.get("id")})
                actions = pb_info.get("actions") if isinstance(pb_info.get("actions"), list) else []
                allowed_actions, governance = _enforce_playbook_actions(actions=actions, action_policy=action_policy)
                append_playbook_step(
                    run_id=run_id,
                    event_type="action_policy",
                    status="completed",
                    evidence={"governance": governance, "lane": action_policy.get("lane")},
                )
                action_exec = execute_typed_actions(run_id=run_id, actions=allowed_actions, context={"channel": "email", "decision_id": decision_id})
                if governance:
                    skipped = list(action_exec.get("skipped") or [])
                    skipped.extend(
                        {
                            "step_index": idx,
                            "action_type": row.get("action_type"),
                            "reason": row.get("reason"),
                            "decision": row.get("decision"),
                        }
                        for idx, row in enumerate(governance)
                        if str(row.get("decision") or "") != "allowed"
                    )
                    action_exec["skipped"] = skipped
                append_playbook_step(run_id=run_id, event_type="actions", status="completed", evidence={"result": action_exec, "governance": governance})
                complete_playbook_run(run_id=run_id, status="completed", outcome="executed")
                v["playbook_run"] = {"run_id": run_id, "actions": action_exec, "governance": governance, "lane": action_policy.get("lane")}
                if isinstance(v.get("evidence_snapshot"), dict):
                    v["evidence_snapshot"]["playbook_run"] = v["playbook_run"]
    except Exception as exc:
        if isinstance(v.get("playbook_run"), dict):
            v["playbook_run"]["status"] = "selected_but_not_started"
            v["playbook_run"]["error"] = str(exc)[:180]
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["playbook_run"] = v.get("playbook_run")

    # Persist incident (redacted) for admin drilldown/grouping
    try:
        meta = extracted.get("meta") if isinstance(extracted, dict) else {}
        supplier_key = (meta or {}).get("from_domain") or (meta or {}).get("reply_to_domain")
    except Exception:
        supplier_key = None
    incident_id = _persist_incident(
        tenant_id=tenant_id,
        provider=str(email.get("provider") or "") or None,
        message_id=str(email.get("message_id") or "") or None,
        conversation_id=str(email.get("conversation_id") or "") or None,
        supplier_key=str(supplier_key) if supplier_key else None,
        ticket_id=ticket_id,
        severity=v.get("severity") or "info",
        risk_band=risk_band,
        tags=list(v.get("tags") or []),
        reasons=list(v.get("reasons") or []),
        evidence_snapshot={
            **dict(v.get("evidence_snapshot") or {}),
            "route": v.get("route"),
            "verdict_action": v.get("verdict_action"),
            "decision_id": decision_id,
            "trace_id": decision_id,
            "ticket_id": ticket_id,
            "policy_gate": v.get("policy_gate"),
        },
        playbook=pb_info if isinstance(pb_info, dict) else None,
        ticket_created=ticket_created,
        ticket_rate_limited=ticket_rate_limited,
        ticket_deduped=ticket_deduped,
    )
    try:
        urls_for_recheck = [str(x.get("value") or "") for x in (v.get("iocs") or []) if str(x.get("type") or "") == "url" and x.get("value")]
        if incident_id and urls_for_recheck:
            from src.app.services.url_recheck_scheduler import schedule_url_rechecks

            recheck_plan = schedule_url_rechecks(
                incident_id=str(incident_id),
                tenant_id=tenant_id,
                decision_id=decision_id,
                urls=urls_for_recheck,
            )
            if isinstance(v.get("evidence_snapshot"), dict):
                v["evidence_snapshot"]["url_recheck"] = recheck_plan
    except Exception:
        pass
    try:
        update_sender_trust(email, extracted, v, tenant_id)
    except Exception:
        pass

    # SIEM/CrowdStrike/CSPM handoff for escalated events (interoperability scope only).
    try:
        if v.get("route") in ("security_review", "human_review"):
            normalized = build_normalized_security_event(
                source="email_security_agent",
                tenant_id=tenant_id,
                decision_id=decision_id,
                trace_id=decision_id,
                message_id_hash=(v.get("evidence_snapshot") or {}).get("message_id_hash"),
                severity=str(v.get("severity") or "info"),
                verdict_action=str(v.get("verdict_action") or "allow"),
                route=str(v.get("route") or "auto_resolve"),
                escalation=str(v.get("escalation") or "none"),
                reasons=list(v.get("reasons") or []),
                tags=list(v.get("tags") or []),
                ioc_counts=((v.get("evidence_snapshot") or {}).get("ioc_counts") or {}),
                risk_band=v.get("risk_band"),
                playbook_id=((v.get("playbook") or {}).get("id") if isinstance(v.get("playbook"), dict) else None),
                ticket_id=ticket_id,
                evidence={
                    "detonation": v.get("detonation"),
                    "enrichment": {"malicious_hits": (v.get("enrichment") or {}).get("malicious_hits")},
                    "policy_gate": v.get("policy_gate"),
                    "trust_case": v.get("trust_case"),
                    "access_policy": v.get("access_policy"),
                    "incident_graph": (v.get("evidence_snapshot") or {}).get("incident_graph"),
                    "vendor_trust_graph": (v.get("evidence_snapshot") or {}).get("vendor_trust_graph"),
                },
            )
            handoff = emit_security_handoff(normalized)
            v["siem_handoff"] = {"event": normalized, "status": handoff}
            if decision_id:
                log_trace_event(
                    trace_id=decision_id,
                    event_type="security_handoff",
                    source_type="agent",
                    source_id="SIEM_Handoff_Adapter",
                    target_type="siem",
                    target_id=None,
                    payload={"status": handoff, "route": v.get("route"), "verdict_action": v.get("verdict_action")},
                )
    except Exception:
        pass

    # Surface DNS auth findings in the response for caller visibility.
    if not dns_auth_result.get("skipped"):
        try:
            v["dns_auth"] = {
                "domain": dns_auth_result.get("domain"),
                "spf_record_found": bool((dns_auth_result.get("spf") or {}).get("available")),
                "dmarc_policy": (dns_auth_result.get("dmarc") or {}).get("policy"),
                "dkim_selector_found": bool((dns_auth_result.get("dkim") or {}).get("available")),
                "discrepancy_count": len(dns_auth_result.get("discrepancy_indicators") or []),
            }
        except Exception:
            pass
    try:
        v["coverage_limits"] = (ransomware_artifact or {}).get("coverage_limits") or ransomware_coverage_limits()
    except Exception:
        v["coverage_limits"] = ransomware_coverage_limits()

    # Surface lookalike domain and thread hijacking findings.
    if lookalike_result.get("detected"):
        try:
            v["lookalike_domain"] = lookalike_result
            # Elevate risk if lookalike detected
            if str(v.get("risk_label") or "").lower() not in ("critical", "high"):
                v["risk_label"] = lookalike_result.get("severity", "high")
        except Exception:
            pass
    if thread_hijack_result.get("detected"):
        try:
            v["thread_hijack"] = thread_hijack_result
            if str(v.get("risk_label") or "").lower() not in ("critical",):
                v["risk_label"] = "high"
        except Exception:
            pass

    # Route suspicious email attachments to the sandbox detonation queue.
    # Complements detonate_targets() (IOC URLs) — covers macro-enabled and
    # executable file types that often bypass URL-only sandbox pipelines.
    _SANDBOX_EXTENSIONS = {
        ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".docm",
        ".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs",
        ".jar", ".pdf", ".lnk", ".hta", ".js",
    }
    _SANDBOX_MIN_BYTES = 10 * 1024  # skip tiny stubs
    try:
        from src.app.services.sandbox_queue import queue_sandbox_detonation
        _trace_id = str(v.get("trace_id") or v.get("decision_id") or "")
        _att_hashes: list[str] = []
        for _att in (email.get("attachments") or []):
            _fname = str(_att.get("filename") or _att.get("name") or "")
            _ext = "." + _fname.rsplit(".", 1)[-1].lower() if "." in _fname else ""
            _size = int(_att.get("size") or _att.get("size_bytes") or 0)
            if _ext in _SANDBOX_EXTENSIONS and _size >= _SANDBOX_MIN_BYTES and _att.get("sha256"):
                _att_hashes.append(str(_att["sha256"]))
        if _att_hashes:
            _sq = queue_sandbox_detonation(
                hypothesis="ransomware",
                trace_id=_trace_id,
                tenant_id=tenant_id,
                decoded_content=None,
                urls=[],
                attachment_hashes=_att_hashes,
                steg_score=0.0,
                source="email_scan",
            )
            v["sandbox_attachment_queued"] = _sq.get("queued", False)
            v["sandbox_attachment_path"] = _sq.get("path")
    except Exception:
        pass

    return v
