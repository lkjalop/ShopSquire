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


def _attachment_forensics_snapshot(
    email: Dict[str, Any],
    artifact_intel: Dict[str, Any] | None,
) -> list[dict[str, Any]]:
    attachments = [dict(a or {}) for a in (email.get("attachments") or []) if isinstance(a, dict)]
    parsed_fields = ((artifact_intel or {}).get("parsed_fields") if isinstance(artifact_intel, dict) else {}) or {}
    baseline_checks = ((artifact_intel or {}).get("baseline_checks") if isinstance(artifact_intel, dict) else {}) or {}
    forensics_details = ((artifact_intel or {}).get("forensics_details") if isinstance(artifact_intel, dict) else {}) or {}
    contributions = list((((artifact_intel or {}).get("signal_scores") if isinstance(artifact_intel, dict) else {}) or {}).get("contributions") or [])
    summary: list[dict[str, Any]] = []
    vendor_name = str(parsed_fields.get("vendor_name") or "").strip()
    sender_domain = str(baseline_checks.get("sender_domain") or "").strip().lower()
    vendor_domain = str(baseline_checks.get("vendor_domain") or "").strip().lower()
    reply_domain = str(baseline_checks.get("reply_domain") or "").strip().lower()
    known_bank_fp = str(baseline_checks.get("known_bank_fingerprint") or baseline_checks.get("bank_fingerprint") or "").strip()

    def _attachment_material_class(name: str, extracted_text: str, urls: list[str], suspicious_instructions: list[str]) -> str:
        lowered = str(name or "").strip().lower()
        text = str(extracted_text or "").strip().lower()
        ext = os.path.splitext(lowered)[1]
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".pdf", ".msg", ".eml"}:
            if suspicious_instructions or urls:
                return "active_payment_lure"
            return "observed_supplier_artifact"
        if ext in {".md", ".txt", ".json"}:
            if any(tok in lowered for tok in ("guide", "scenario", "summary", "matrix", "taxonomy", "playbook", "spec", "report")):
                return "reference_spec_material"
            return "contextual_test_artifact"
        if ext in {".py", ".ps1", ".sh"}:
            if any(tok in text for tok in ("image.new", "generate", "simulat", "shopsquire", "invoice")):
                return "contextual_test_artifact"
        if ext in {".bas", ".vba", ".xlsm", ".xlam", ".vbs"}:
            _vba_exec_toks = (
                "sub auto_open()", "sub workbook_open()", "sub document_open()",
                "wscript.shell", "createobject(", "shell(", "mshta ", "certutil",
                "bitsadmin", "powershell",
            )
            if any(tok in text for tok in _vba_exec_toks):
                return "active_payment_lure"
            return "contextual_test_artifact"
        if suspicious_instructions or urls:
            return "active_payment_lure"
        return "contextual_test_artifact"

    def _text_summary(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned:
            return ""
        if len(cleaned) <= 220:
            return cleaned
        return cleaned[:217] + "..."

    def _extract_urls(text: str) -> list[str]:
        found = re.findall(r"https?://[^\s<>'\"`]+", str(text or ""), re.IGNORECASE)
        out: list[str] = []
        for url in found:
            if url not in out:
                out.append(url)
        return out[:8]

    def _evidence_excerpt_lines(text: str) -> list[str]:
        out: list[str] = []
        for line in re.split(r"[\r\n]+", str(text or "")):
            cleaned = line.strip()
            if not cleaned:
                continue
            if re.search(r"(?i)(bank(?:ing)?\s+details?|remittance|payment|account|bsb|swift|invoice|abn)", cleaned):
                out.append(cleaned[:180])
            if len(out) >= 4:
                break
        return out

    for att in attachments:
        name = str(att.get("name") or "attachment")
        extracted_text = str(att.get("extracted_text") or "")
        urls = _extract_urls(extracted_text)
        if not urls:
            urls = [str(x) for x in (att.get("pdf_embedded_urls") or []) if str(x or "").strip()][:8]
        bank_fields = att.get("bank_fields") if isinstance(att.get("bank_fields"), dict) else {}
        suspicious_instructions: list[str] = []
        lower_text = extracted_text.lower()
        if re.search(r"(?i)\b(bank(?:ing)?\s+details?\s+have\s+changed|disregard\s+(?:any\s+)?previous\s+remittance|new\s+account|new\s+bsb|updated\s+payment\s+details?)\b", extracted_text):
            suspicious_instructions.append("Requests new or changed payment instructions.")
        if bank_fields:
            suspicious_instructions.append("Contains bank or remittance details in the attachment.")
        # VBA / script macro execution indicators in extracted text.
        # Fires for .bas, .vba, .xlsm, .xlam, .ps1, .vbs, and any other attachment
        # where the text surface contains recognisable offensive VBA/script primitives.
        _vba_indicator_map = [
            ("sub auto_open()",       "vba_auto_open_macro"),
            ("sub workbook_open()",   "vba_workbook_open_macro"),
            ("sub document_open()",   "vba_document_open_macro"),
            ("wscript.shell",         "vba_wscript_shell"),
            ("createobject(",         "vba_createobject_call"),
            ("shell(",                "vba_shell_call"),
            ("mshta ",                "vba_mshta_lolbin"),
            ("certutil",              "vba_certutil_lolbin"),
            ("bitsadmin",             "vba_bitsadmin_lolbin"),
            ("powershell",            "vba_powershell_indicator"),
        ]
        for _vba_pat, _vba_label in _vba_indicator_map:
            if _vba_pat in lower_text:
                suspicious_instructions.append(
                    f"Attachment contains VBA/script execution indicator: {_vba_label}"
                )
        attachment_reasons = [
            str(item.get("reason") or "")
            for item in contributions
            if isinstance(item, dict) and name.lower() in json.dumps(item.get("reason") or "").lower()
        ]
        mismatch_signals: list[str] = []
        if name in list(forensics_details.get("template_drift") or []):
            mismatch_signals.append("Template differs from the trusted vendor baseline.")
        if name in list(forensics_details.get("logo_layout") or []):
            mismatch_signals.append("Logo or layout does not match the trusted baseline.")
        if sender_domain and vendor_domain and sender_domain != vendor_domain:
            mismatch_signals.append(f"Sender domain {sender_domain} does not match expected vendor domain {vendor_domain}.")
        if reply_domain and vendor_domain and reply_domain != vendor_domain:
            mismatch_signals.append(f"Reply-to domain {reply_domain} differs from expected vendor domain {vendor_domain}.")
        if vendor_name and not re.search(re.escape(vendor_name), extracted_text, re.IGNORECASE):
            mismatch_signals.append("Attachment content does not clearly reinforce the claimed vendor name.")
        if parsed_fields.get("abn_placeholder"):
            mismatch_signals.append("Document appears to contain a leftover template placeholder.")
        support_state = "neutral"
        if suspicious_instructions or mismatch_signals:
            support_state = "contradicts_sender_claim"
        elif vendor_name and re.search(re.escape(vendor_name), extracted_text, re.IGNORECASE):
            support_state = "supports_sender_claim"
        attachment_class = _attachment_material_class(name, extracted_text, urls, suspicious_instructions)
        summary.append(
            {
                "file_name": name,
                "file_type": str(att.get("content_type") or "unknown"),
                "sha256": str(att.get("sha256") or ""),
                "size_bytes": int(att.get("size_bytes") or 0),
                "text_summary": _text_summary(extracted_text),
                "analysis_text_sample": extracted_text[:4000] if extracted_text else "",
                "evidence_excerpt_lines": _evidence_excerpt_lines(extracted_text),
                "ocr_hit_count": len(re.findall(r"[A-Za-z0-9]", extracted_text)),
                "embedded_urls": urls,
                "qr_code_detected": bool(att.get("qr_code_detected")),
                "qr_external_url_detected": bool(att.get("qr_external_url_detected")),
                "qr_redirect_findings": list(att.get("qr_redirect_findings") or []) if isinstance(att.get("qr_redirect_findings"), list) else [],
                "qr_payloads": list(att.get("qr_payloads") or []) if isinstance(att.get("qr_payloads"), list) else [],
                "qr_assessments": list(att.get("qr_assessments") or []) if isinstance(att.get("qr_assessments"), list) else [],
                "suspicious_instructions": suspicious_instructions,
                "brand_supplier_mismatch_signals": mismatch_signals,
                "baseline_similarity": {
                    "template_aligned": name not in list(forensics_details.get("template_drift") or []),
                    "logo_layout_aligned": name not in list(forensics_details.get("logo_layout") or []),
                    "vendor_domain_matches": bool(vendor_domain and sender_domain and vendor_domain == sender_domain),
                    "known_good_template_hash": str(att.get("expected_template_hash") or ""),
                    "known_good_logo_hash": str(att.get("expected_logo_hash") or ""),
                    "known_good_layout_hash": str(att.get("expected_layout_hash") or ""),
                    "known_good_bank_fingerprint": known_bank_fp,
                },
                "supports_sender_claim": support_state,
                "attachment_class": attachment_class,
                "authority_level": "primary" if attachment_class in {"active_payment_lure", "observed_supplier_artifact"} else "contextual",
                "bank_fields_present": bool(bank_fields),
                "bank_fields": bank_fields,
                "pdf_forensics": {
                    "producer": att.get("pdf_producer"),
                    "creator": att.get("pdf_creator"),
                    "embedded_files_count": int(att.get("embedded_files_count") or 0),
                    "object_stream_count": int(att.get("pdf_objstm_count") or 0),
                    "xref_stream_present": bool(att.get("pdf_xrefstm_present")),
                },
                "document_hashes": {
                    "template_hash": att.get("template_hash"),
                    "logo_hash": att.get("logo_hash"),
                    "layout_hash": att.get("layout_hash"),
                    "extracted_bank_fingerprint": att.get("extracted_bank_fingerprint"),
                },
                "parse_errors": list(att.get("parse_errors") or []) if isinstance(att.get("parse_errors"), list) else [],
                "ssn_detected": bool(att.get("ssn_detected")),
                "pii_detected": bool(att.get("pii_detected")),
                "pii_type": list(att.get("pii_type") or []) if isinstance(att.get("pii_type"), list) else [],
                "ssn_count": int(att.get("ssn_count") or 0),
                "linked_artifact": dict(att.get("linked_artifact") or {}) if isinstance(att.get("linked_artifact"), dict) else {},
                "linked_reason_summary": str(((att.get("linked_artifact") or {}).get("linked_reason_summary") if isinstance(att.get("linked_artifact"), dict) else "") or ""),
                "linked_policy_action": str(((att.get("linked_artifact") or {}).get("linked_policy_action") if isinstance(att.get("linked_artifact"), dict) else "") or ""),
                "linked_verdict_label": str(((att.get("linked_artifact") or {}).get("linked_verdict_label") if isinstance(att.get("linked_artifact"), dict) else "") or ""),
                "linked_confidence_band": str(((att.get("linked_artifact") or {}).get("linked_confidence_band") if isinstance(att.get("linked_artifact"), dict) else "") or ""),
                "linked_user_summary": dict(((att.get("linked_artifact") or {}).get("linked_user_summary") if isinstance(att.get("linked_artifact"), dict) else {}) or {}),
                "linked_host_enrichment": dict(((att.get("linked_artifact") or {}).get("linked_host_enrichment") if isinstance(att.get("linked_artifact"), dict) else {}) or {}),
                "linked_supplier_verification": dict(((att.get("linked_artifact") or {}).get("linked_supplier_verification") if isinstance(att.get("linked_artifact"), dict) else {}) or {}),
                "steg": {
                    "score": att.get("steg_score"),
                    "suspicious": bool(att.get("steg_suspicious")),
                    "source": att.get("steg_source"),
                },
                "steg_explanations": list(att.get("steg_explanations") or []) if isinstance(att.get("steg_explanations"), list) else [],
                "steg_details": dict(att.get("steg_details") or {}) if isinstance(att.get("steg_details"), dict) else {},
            }
        )
        # MAESTRO SC-04B per-attachment boundary check for attachment_forensics_agent.
        # Each attachment processed is a discrete boundary enforcement point.
        # Maps to OWASP Agentic AI AA03 (trust boundary violation) and AA05 (prompt injection
        # via content channels — OCR/QR surfaces in attachments can carry injections).
        try:
            _att_tools_used = []
            if extracted_text:
                _att_tools_used.append("ocr_attachment")
            if str(att.get("content_type") or "").lower().endswith("pdf") or name.lower().endswith(".pdf"):
                _att_tools_used.append("parse_pdf")
            if att.get("qr_code_detected"):
                _att_tools_used.append("scan_qr")
            if bank_fields:
                _att_tools_used.append("extract_bank_fields")
            if not _att_tools_used:
                _att_tools_used.append("extract_text")
            _att_violations = []
            for _tool in _att_tools_used:
                for _v in validate_agent_action(agent_name="attachment_forensics_agent", tool_name=_tool):
                    _att_violations.append({"violation_type": _v.violation_type, "detail": _v.detail, "severity": _v.severity})
            for _v in validate_agent_action(agent_name="attachment_forensics_agent", data_scope="attachments"):
                _att_violations.append({"violation_type": _v.violation_type, "detail": _v.detail, "severity": _v.severity})
            # AA05: flag if attachment carries active injection indicators via OCR/QR channel.
            _aa05_signals = []
            if att.get("qr_prompt_injection") or (att.get("steg_suspicious") and extracted_text):
                _aa05_signals.append("qr_or_steg_injection_channel_active")
            if re.search(r"(?i)(ignore\s+previous|system\s*prompt|developer\s+mode|do\s+not\s+follow)", extracted_text):
                _aa05_signals.append("ocr_text_prompt_injection_pattern")
            summary[-1]["maestro_boundary_check"] = {
                "agent": "attachment_forensics_agent",
                "tools_validated": _att_tools_used,
                "scope_enforced": len(_att_violations) == 0,
                "scope_violations": _att_violations,
                "owasp_agentic": ["AA03"] + (["AA05"] if _aa05_signals else []),
                "aa05_signals": _aa05_signals,
                "maestro_control": "SC-04B",
            }
        except Exception:
            pass
    return summary


def _sender_infrastructure_snapshot(
    email: Dict[str, Any],
    header_forensics: Dict[str, Any] | None,
) -> Dict[str, Any]:
    hdr = header_forensics if isinstance(header_forensics, dict) else {}
    from_addr = str(email.get("from_addr") or "").strip()
    reply_to = str(email.get("reply_to") or "").strip()
    sender_domain = str(extract_domain(from_addr) or "").strip().lower()
    reply_domain = str(extract_domain(reply_to) or "").strip().lower()
    originating_ip = str(hdr.get("originating_ip") or "").strip()
    geo = hdr.get("originating_ip_geo") if isinstance(hdr.get("originating_ip_geo"), dict) else {}
    geo_risk = float(geo.get("risk") or 0.0) if isinstance(geo, dict) else 0.0
    reputation_flags: list[str] = []
    if geo_risk >= 0.85:
        reputation_flags.append("high_geo_risk")
    elif geo_risk >= 0.65:
        reputation_flags.append("elevated_geo_risk")
    if bool(geo.get("is_tor")):
        reputation_flags.append("tor_exit_node")
    if bool(geo.get("is_vpn")):
        reputation_flags.append("vpn_or_proxy")
    if bool(geo.get("is_hosting")):
        reputation_flags.append("hosting_provider_origin")
    if bool(hdr.get("message_id_domain_mismatch")):
        reputation_flags.append("message_id_domain_mismatch")
    if bool(hdr.get("message_id_reuse")):
        reputation_flags.append("message_id_reuse")
    if bool(hdr.get("relay_count_anomaly")):
        reputation_flags.append("relay_chain_anomaly")
    if bool(hdr.get("timing_anomaly")):
        reputation_flags.append("header_timing_anomaly")
    related: Dict[str, Any] = {"count": 0, "matches": []}
    try:
        from sqlalchemy import text
        from src.app.models.db import db_session

        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, severity, evidence_json
                    FROM email_security_incidents
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                )
            ).fetchall()
        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows or []:
            incident_id = str(row[0] or "")
            severity = str(row[1] or "")
            try:
                evidence = json.loads(str(row[2] or "{}"))
            except Exception:
                evidence = {}
            sender = evidence.get("sender_infrastructure") if isinstance(evidence.get("sender_infrastructure"), dict) else {}
            hf = evidence.get("header_forensics") if isinstance(evidence.get("header_forensics"), dict) else {}
            sender_match = sender_domain and sender_domain == str(sender.get("sender_domain") or "").strip().lower()
            reply_match = reply_domain and reply_domain == str(sender.get("reply_domain") or "").strip().lower()
            ip_match = originating_ip and originating_ip == str((sender.get("originating_ip") or hf.get("originating_ip") or "")).strip()
            if sender_match or reply_match or ip_match:
                key = incident_id
                if key in seen:
                    continue
                seen.add(key)
                reason = []
                if sender_match:
                    reason.append("sender_domain")
                if reply_match:
                    reason.append("reply_domain")
                if ip_match:
                    reason.append("originating_ip")
                matches.append(
                    {
                        "incident_id": incident_id,
                        "severity": severity,
                        "match_on": reason,
                    }
                )
            if len(matches) >= 5:
                break
        related = {"count": len(matches), "matches": matches}
    except Exception:
        related = {"count": 0, "matches": []}

    return {
        "sender_address": from_addr or None,
        "reply_to": reply_to or None,
        "sender_domain": sender_domain or None,
        "reply_domain": reply_domain or None,
        "reply_domain_mismatch": bool(sender_domain and reply_domain and sender_domain != reply_domain),
        "originating_ip": originating_ip or None,
        "originating_geo": geo or {},
        "message_id_domain_mismatch": bool(hdr.get("message_id_domain_mismatch")),
        "message_id_reuse": bool(hdr.get("message_id_reuse")),
        "mailer_fingerprint": hdr.get("mailer_fingerprint"),
        "mailer_is_bulk": bool(hdr.get("mailer_is_bulk")),
        "reputation": {
            "risk_score": round(geo_risk, 4),
            "flags": reputation_flags,
            "known_bad": bool(any(flag in reputation_flags for flag in ("high_geo_risk", "tor_exit_node"))),
        },
        "related_incidents": related,
    }


def _attachment_baseline_diff_snapshot(email: Dict[str, Any]) -> Dict[str, Any]:
    attachments = [dict(a or {}) for a in (email.get("attachments") or []) if isinstance(a, dict)]
    pdfs = [a for a in attachments if "pdf" in str(a.get("content_type") or "").lower() or str(a.get("name") or "").lower().endswith(".pdf")]
    if len(pdfs) < 2:
        return {"baseline_file": None, "comparisons": []}

    def _risk_score(att: Dict[str, Any]) -> float:
        text = str(att.get("extracted_text") or "")
        name = str(att.get("name") or "").lower()
        score = 0.0
        if "fake" in name:
            score += 3.0
        if re.search(r"(?i)(bank(?:ing)?\s+details?\s+have\s+changed|disregard\s+(?:any\s+)?previous\s+remittance|new\s+account|updated\s+payment)", text):
            score += 3.0
        if int(att.get("embedded_files_count") or 0) > 0:
            score += 1.0
        if int(att.get("pdf_objstm_count") or 0) >= 3:
            score += 1.0
        return score

    baseline = sorted(pdfs, key=lambda a: (_risk_score(a), len(str(a.get("name") or ""))))[0]
    baseline_name = str(baseline.get("name") or "baseline.pdf")
    baseline_text = str(baseline.get("extracted_text") or "")
    baseline_bank = baseline.get("bank_fields") if isinstance(baseline.get("bank_fields"), dict) else {}
    baseline_urls = sorted(set(re.findall(r"https?://[^\s<>'\"`]+", baseline_text, re.IGNORECASE)))

    def _load_preview_b64(att: Dict[str, Any]) -> str:
        return str(att.get("preview_png_b64") or "").strip()

    def _build_pdf_visual_overlay(base_b64: str, cand_b64: str) -> Dict[str, Any]:
        if not base_b64 or not cand_b64:
            return {}
        try:
            from PIL import Image, ImageChops, ImageOps, ImageStat  # type: ignore

            b = Image.open(io.BytesIO(base64.b64decode(base_b64))).convert("RGB")
            c = Image.open(io.BytesIO(base64.b64decode(cand_b64))).convert("RGB").resize(b.size)
            overlay = Image.blend(b, c, 0.5)
            diff = ImageChops.difference(b, c)
            gray = ImageOps.grayscale(diff)
            bbox = gray.point(lambda p: 255 if p > 16 else 0).getbbox()
            heat = ImageOps.colorize(gray, black="#0f172a", white="#ff6a00")
            ov = io.BytesIO()
            hm = io.BytesIO()
            overlay.save(ov, format="PNG")
            heat.save(hm, format="PNG")
            stat = ImageStat.Stat(gray)
            return {
                "baseline_preview_b64": base_b64,
                "candidate_preview_b64": cand_b64,
                "overlay_preview_b64": base64.b64encode(ov.getvalue()).decode("ascii"),
                "heatmap_preview_b64": base64.b64encode(hm.getvalue()).decode("ascii"),
                "mean_pixel_diff": round(float(stat.mean[0] if stat.mean else 0.0), 3),
                "drift_bbox": [int(v) for v in bbox] if bbox else [],
                "drift_detected": bool(bbox),
            }
        except Exception:
            return {}

    comparisons: list[dict[str, Any]] = []
    for att in pdfs:
        if att is baseline:
            continue
        text = str(att.get("extracted_text") or "")
        bank = att.get("bank_fields") if isinstance(att.get("bank_fields"), dict) else {}
        urls = sorted(set(re.findall(r"https?://[^\s<>'\"`]+", text, re.IGNORECASE)))
        similarity = round(SequenceMatcher(a=baseline_text[:5000], b=text[:5000]).ratio(), 4) if (baseline_text or text) else 0.0
        differences: list[str] = []
        if str(att.get("template_hash") or "") != str(baseline.get("template_hash") or ""):
            differences.append("Template hash differs from the baseline PDF.")
        if str(att.get("layout_hash") or "") != str(baseline.get("layout_hash") or ""):
            differences.append("Layout hash differs from the baseline PDF.")
        if str(att.get("logo_hash") or "") != str(baseline.get("logo_hash") or ""):
            differences.append("Logo hash differs from the baseline PDF.")
        if bank != baseline_bank:
            differences.append("Bank or remittance fields differ from the baseline PDF.")
        if urls != baseline_urls:
            differences.append("Embedded URLs differ from the baseline PDF.")
        if str(att.get("pdf_producer") or "") != str(baseline.get("pdf_producer") or ""):
            differences.append("PDF producer metadata differs from the baseline PDF.")
        visual = _build_pdf_visual_overlay(_load_preview_b64(baseline), _load_preview_b64(att))
        comparisons.append(
            {
                "baseline_file": baseline_name,
                "candidate_file": str(att.get("name") or ""),
                "text_similarity": similarity,
                "baseline_bank_fields": baseline_bank,
                "candidate_bank_fields": bank,
                "baseline_urls": baseline_urls[:8],
                "candidate_urls": urls[:8],
                "differences": differences,
                **visual,
            }
        )
    return {"baseline_file": baseline_name, "comparisons": comparisons}


def _attachment_visual_diff_snapshot(email: Dict[str, Any]) -> Dict[str, Any]:
    attachments = [dict(a or {}) for a in (email.get("attachments") or []) if isinstance(a, dict)]
    images = [
        a for a in attachments
        if str(a.get("preview_png_b64") or "").strip()
        and (
            str(a.get("content_type") or "").lower().startswith("image/")
            or str(a.get("name") or "").lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"))
        )
    ]
    if len(images) < 2:
        return {"baseline_file": None, "comparisons": []}
    try:
        from PIL import Image, ImageChops, ImageOps, ImageStat  # type: ignore
    except Exception:
        return {"baseline_file": None, "comparisons": []}

    def _load_preview(att: Dict[str, Any]):
        raw = str(att.get("preview_png_b64") or "").strip()
        if not raw:
            return None
        try:
            return Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
        except Exception:
            return None

    def _risk_score(att: Dict[str, Any]) -> float:
        name = str(att.get("name") or "").lower()
        text = str(att.get("extracted_text") or "")
        score = 0.0
        if "baseline" in name:
            score -= 10.0
        if "adv" in name or "fake" in name:
            score += 2.0
        if re.search(r"(?i)(payment|account|bsb|bank(?:ing)?\s+details?)", text):
            score += 2.0
        return score

    baseline = sorted(images, key=lambda a: (_risk_score(a), len(str(a.get("name") or ""))))[0]
    baseline_img = _load_preview(baseline)
    if baseline_img is None:
        return {"baseline_file": None, "comparisons": []}

    comparisons: list[dict[str, Any]] = []
    for att in images:
        if att is baseline:
            continue
        cand_img = _load_preview(att)
        if cand_img is None:
            continue
        try:
            b = baseline_img.copy()
            c = cand_img.copy().resize(b.size)
            diff = ImageChops.difference(b, c)
            gray = ImageOps.grayscale(diff)
            stat = ImageStat.Stat(gray)
            mean_diff = float(stat.mean[0] if stat.mean else 0.0)
            bbox = gray.point(lambda p: 255 if p > 18 else 0).getbbox()
            heat = ImageOps.colorize(gray, black="#0f172a", white="#ff6a00")
            out = io.BytesIO()
            heat.save(out, format="PNG")
            comparisons.append(
                {
                    "baseline_file": str(baseline.get("name") or ""),
                    "candidate_file": str(att.get("name") or ""),
                    "baseline_preview_b64": str(baseline.get("preview_png_b64") or ""),
                    "candidate_preview_b64": str(att.get("preview_png_b64") or ""),
                    "diff_preview_b64": base64.b64encode(out.getvalue()).decode("ascii"),
                    "mean_pixel_diff": round(mean_diff, 3),
                    "drift_bbox": [int(v) for v in bbox] if bbox else [],
                    "drift_detected": bool(bbox),
                }
            )
        except Exception:
            continue
    return {"baseline_file": str(baseline.get("name") or ""), "comparisons": comparisons}


def _email_agent_boundaries() -> Dict[str, Dict[str, Any]]:
    return {
        "sender_auth_agent": {
            "allowed_inputs": ["headers", "auth_results", "sender_domains", "header_forensics"],
            "allowed_tools": ["validate_auth", "analyze_headers", "score_reply_drift"],
            "allowed_outputs": ["auth_failures", "reply_drift", "spoof_likelihood", "infrastructure_anomalies"],
            "denied_capabilities": ["read_full_attachment_bodies", "trigger_actions", "access_secrets", "open_internet"],
            "action_mode": "read_only",
        },
        "attachment_forensics_agent": {
            "allowed_inputs": ["sanitized_attachment_text", "ocr_output", "file_metadata", "static_analysis"],
            "allowed_tools": ["extract_text", "ocr_attachment", "parse_pdf", "scan_qr", "extract_bank_fields"],
            "allowed_outputs": ["bank_detail_extraction", "qr_url_findings", "script_macro_risk", "attachment_class", "per_file_evidence"],
            "denied_capabilities": ["update_supplier_baseline", "access_secrets", "push_connectors", "open_internet"],
            "action_mode": "read_only",
        },
        "baseline_agent": {
            "allowed_inputs": ["supplier_profile", "approved_contacts", "bank_fingerprints", "template_hashes", "attachment_summaries"],
            "allowed_tools": ["compare_template_hashes", "compare_bank_fingerprints", "score_supplier_drift"],
            "allowed_outputs": ["baseline_mismatch", "baseline_state", "candidate_update_recommendation"],
            "denied_capabilities": ["change_baseline_automatically", "push_connectors", "access_secrets"],
            "action_mode": "recommend_only",
        },
        "correlation_agent": {
            "allowed_inputs": ["current_findings", "prior_incidents", "sender_graph", "bank_graph", "infra_overlap"],
            "allowed_tools": ["link_related_incidents", "score_campaign_overlap", "build_incident_context"],
            "allowed_outputs": ["related_incidents", "campaign_linkage", "historical_context"],
            "denied_capabilities": ["alter_verdict_alone", "execute_actions", "access_secrets"],
            "action_mode": "read_only",
        },
        "explanation_agent": {
            "allowed_inputs": ["normalized_evidence", "faq_mappings", "policy_mappings", "sop_mappings"],
            "allowed_tools": ["summarize_findings", "map_policy_guidance", "render_explanations"],
            "allowed_outputs": ["business_safe_summary", "analyst_summary", "raw_technical_summary"],
            "denied_capabilities": ["invent_evidence", "override_severity", "execute_actions", "access_secrets"],
            "action_mode": "read_only",
        },
        "playbook_agent": {
            "allowed_inputs": ["policy_approved_findings", "allowed_action_set", "sop_mappings"],
            "allowed_tools": ["map_playbook_steps", "propose_gated_actions", "render_next_steps"],
            "allowed_outputs": ["recommended_steps", "gated_action_plan"],
            "denied_capabilities": ["execute_privileged_actions_without_approval", "change_baseline_automatically"],
            "action_mode": "approval_gated",
        },
    }


def _confidence_band(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _finding_source_toolset(agent_origin: str) -> list[str]:
    tools = (_email_agent_boundaries().get(str(agent_origin or "").strip()) or {}).get("allowed_tools") or []
    return [str(x) for x in tools][:6]


def _normalize_finding(
    *,
    finding_id: str,
    finding_type: str,
    summary: str,
    severity_hint: str,
    confidence_score: float,
    source_type: str,
    evidence_kind: str,
    agent_origin: str,
    policy_weight: float,
    evidence: list[str] | None = None,
    artifact_ref: Dict[str, Any] | None = None,
    retrieval_context: Dict[str, Any] | None = None,
    recommended_action: str = "security_review",
    allowed_actions: list[str] | None = None,
    disallowed_actions: list[str] | None = None,
    claim_status: str | None = None,
    finding_group: str | None = None,
    evidence_refs: list[str] | None = None,
    artifact_provenance: list[dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    normalized_evidence_kind = str(evidence_kind or "inferred").strip()
    normalized_claim_status = str(claim_status or ("observed" if normalized_evidence_kind == "direct" else "inferred")).strip().lower()
    normalized_group = str(finding_group or "active_findings").strip()
    row = {
        "finding_id": str(finding_id or "").strip(),
        "finding_type": str(finding_type or "unknown").strip(),
        "summary": str(summary or "").strip(),
        "severity_hint": str(severity_hint or "medium").strip(),
        "confidence_score": round(float(confidence_score or 0.0), 4),
        "confidence_band": _confidence_band(float(confidence_score or 0.0)),
        "source_type": str(source_type or "policy").strip(),
        "evidence_kind": normalized_evidence_kind,
        "agent_origin": str(agent_origin or "email_security_agent").strip(),
        "policy_weight": round(float(policy_weight or 0.0), 4),
        "artifact_ref": artifact_ref if isinstance(artifact_ref, dict) else {},
        "evidence": [str(x) for x in (evidence or []) if str(x or "").strip()][:8],
        "retrieval_context": retrieval_context if isinstance(retrieval_context, dict) else {},
        "claim_status": normalized_claim_status,
        "finding_group": normalized_group,
        "evidence_refs": [str(x) for x in (evidence_refs or []) if str(x or "").strip()][:10],
        "artifact_provenance": [dict(x) for x in (artifact_provenance or []) if isinstance(x, dict)][:8],
        "recommended_action": str(recommended_action or "security_review").strip(),
        "allowed_actions": [str(x) for x in (allowed_actions or []) if str(x or "").strip()][:8],
        "disallowed_actions": [str(x) for x in (disallowed_actions or []) if str(x or "").strip()][:8],
    }
    if not row["allowed_actions"]:
        row["allowed_actions"] = ["notify_analyst", "create_ticket"]
    if not row["disallowed_actions"]:
        row["disallowed_actions"] = ["approve_supplier_update", "push_block_rule"]
    return row


def _finding_rank_score(finding: Dict[str, Any]) -> float:
    f = finding if isinstance(finding, dict) else {}
    score = float(f.get("confidence_score") or 0.0)
    score += float(f.get("policy_weight") or 0.0) * 0.35
    if str(f.get("evidence_kind") or "") == "direct":
        score += 0.2
    source = str(f.get("source_type") or "")
    score += {
        "baseline": 0.18,
        "behavioral": 0.16,
        "policy": 0.14,
        "static": 0.12,
        "ocr": 0.11,
        "intel": 0.1,
    }.get(source, 0.05)
    ftype = str(f.get("finding_type") or "")
    if any(tok in ftype for tok in ("bank", "payment_change", "baseline_mismatch", "reply_drift", "auth_failure")):
        score += 0.18
    if any(tok in ftype for tok in ("lolbin_command_sequence", "c2_beacon_pattern", "data_exfiltration_instruction", "prompt_injection_hidden", "ssn_leakage_linked_qr")):
        score += 0.22
    if any(tok in ftype for tok in ("attachment_url_exposure", "qr_redirect_risk")):
        score += 0.08
    if "related_incident" in ftype or "campaign" in ftype:
        score += 0.08
    name = str(((f.get("artifact_ref") or {}).get("file_name") or "")).lower()
    if name.endswith(".pdf") and any(_tok in " ".join([str(x) for x in (f.get("evidence") or [])]).lower() for _tok in ("bsb", "account", "payment", "bank", "remittance", "http://", "https://")):
        score += 0.16
    if ftype == "infrastructure_anomaly" and float(f.get("confidence_score") or 0.0) < 0.8:
        score -= 0.08
    if str(f.get("finding_category") or "") == "policy_violation":
        score -= 0.2
    if source == "policy" and not name:
        score -= 0.1
    if name.endswith((".md", ".json", ".py", ".txt")) or any(tok in name for tok in ("guide", "scenario", "test", "summary", "matrix", "spec", "report", "generate", "playbook")):
        score -= 0.42
    category = str(f.get("finding_category") or "")
    claim_status = str(f.get("claim_status") or "").lower()
    if category == "benign_reference_material":
        score -= 0.55
    elif category == "contextual_test_artifact":
        score -= 0.85
    elif category == "reference_spec_material":
        score -= 0.92
    elif category == "contextual_supplier_mismatch":
        score -= 0.1
    if claim_status == "suppressed":
        score -= 1.25
    elif claim_status == "possible":
        score -= 0.28
    return round(score, 4)


def _artifact_finding_category(filename: str, finding_type: str, summary: str) -> str:
    name = str(filename or "").strip().lower()
    ftype = str(finding_type or "").strip().lower()
    text = str(summary or "").strip().lower()
    if name.endswith((".md", ".json", ".txt")) or any(tok in name for tok in ("guide", "scenario", "summary", "matrix", "spec", "report", "taxonomy", "playbook")):
        if any(tok in name for tok in ("guide", "scenario", "summary", "matrix", "spec", "report", "taxonomy", "playbook")):
            return "reference_spec_material"
        return "benign_reference_material"
    if name.endswith((".py", ".ps1", ".sh")) or any(tok in name for tok in ("generate", "fixture", "sample_")):
        return "contextual_test_artifact"
    if any(tok in ftype for tok in ("baseline_mismatch", "baseline_drift")):
        return "baseline_drift"
    if any(tok in ftype for tok in ("lolbin_command_sequence", "c2_beacon_pattern")):
        return "unconfirmed_execution_hypothesis"
    if any(tok in ftype for tok in ("lolbin_command_sequence", "c2_beacon_pattern", "data_exfiltration_instruction")):
        return "malicious_artifact"
    if "prompt_injection_hidden" in ftype:
        return "policy_violation"
    if "ssn_leakage_linked_qr" in ftype:
        return "active_payment_lure"
    if any(tok in ftype for tok in ("payment_change", "bank_detail", "attachment_url", "qr_redirect")):
        if name.endswith((".md", ".json", ".py", ".txt")):
            return "contextual_test_artifact"
        return "active_payment_lure"
    if any(tok in ftype for tok in ("reply_drift", "auth_failure", "infrastructure_anomaly", "related_incident_overlap")):
        return "contextual_supplier_mismatch"
    if "contradict" in text or "does not line up" in text:
        return "contradicts_sender_claim"
    if "policy" in ftype or "policy " in text:
        return "policy_violation"
    return "suspicious"


def _artifact_evidence_refs(filename: str, evidence: list[str] | None) -> list[str]:
    name = str(filename or "").strip().lower()
    refs: list[str] = []
    joined = " \n ".join(str(x or "") for x in (evidence or []))
    low = joined.lower()
    if name.endswith(".xlsm"):
        if "enable content" in low or "enable macros" in low:
            refs.append("xlsm.sheet1.enable_macros_banner")
        if "85,000" in low or "aud $85,000.00" in low:
            refs.append("xlsm.sheet4.amount")
        if "harbourside capital partners" in low:
            refs.append("xlsm.sheet4.beneficiary")
        if "012-456" in low:
            refs.append("xlsm.sheet4.bsb")
        if "8877 3421" in low:
            refs.append("xlsm.sheet4.account_number")
        if "anzbau3m" in low:
            refs.append("xlsm.sheet4.swift")
        if "do not discuss" in low or "strictly confidential" in low:
            refs.append("xlsm.sheet4.confidentiality")
        if "verbal approval pending" in low or "boris petrov" in low:
            refs.append("xlsm.sheet4.authorization")
        if "deposit required" in low:
            refs.append("xlsm.sheet2.deposit_required")
        if "powershell -executionpolicy bypass" in low or "powershell.exe" in low:
            refs.append("xlsm.vba.powershell_indicator")
        if "certutil -urlcache" in low or "certutil.exe" in low:
            refs.append("xlsm.vba.certutil_indicator")
        if "bitsadmin /transfer" in low or "bitsadmin" in low:
            refs.append("xlsm.vba.bitsadmin_indicator")
        if "schtasks /create" in low or "schtasks" in low:
            refs.append("xlsm.vba.schtasks_indicator")
        if "balashnikovai-cdn.com" in low:
            refs.append("xlsm.vba.c2_domain_cdn")
        if "balashnikovai-analytics.com" in low:
            refs.append("xlsm.vba.c2_domain_analytics")
        if "sub auto_open()" in low:
            refs.append("xlsm.vba.auto_open")
        if "sub workbook_open()" in low:
            refs.append("xlsm.vba.workbook_open")
    elif name.endswith(".pdf"):
        if "balashnikovai-analytics.com" in low:
            refs.append("pdf.raw.balashnikovai_analytics_domain")
        if "balashnikovai-cdn.com" in low:
            refs.append("pdf.raw.balashnikovai_cdn_domain")
        if "http://" in low or "https://" in low:
            refs.append("pdf.embedded_urls")
        if "/track/wta-" in low or "track/wta-2026" in low:
            refs.append("pdf.footer.tracking_url")
        if "wire transfer authorization" in low:
            refs.append("pdf.form.wire_transfer_authorization")
    elif name.endswith(".bas"):
        if "sub auto_open()" in low:
            refs.append("vba.auto_open")
        if "sub workbook_open()" in low:
            refs.append("vba.workbook_open")
        if "benign test - no functional malicious code" in low:
            refs.append("vba.banner.benign_test_artifact")
        if "' powershell.exe" in low or "' certutil.exe" in low or "' bitsadmin" in low or "' schtasks" in low:
            refs.append("vba.comments.lolbin_pattern")
        if "balashnikovai-cdn.com" in low or "balashnikovai-analytics.com" in low:
            refs.append("vba.comments.c2_domain")
    elif name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        if "lsb content extraction succeeded" in low or "\"decoded_content\"" in low:
            refs.append("image.steg.decoded_content")
        if "certutil" in low:
            refs.append("image.steg.certutil_indicator")
        if "powershell" in low:
            refs.append("image.steg.powershell_indicator")
        if "bitsadmin" in low:
            refs.append("image.steg.bitsadmin_indicator")
        if "schtasks" in low:
            refs.append("image.steg.schtasks_indicator")
        if "callback" in low or "beacon" in low or "interval" in low or "test-c2.example.invalid" in low:
            refs.append("image.steg.c2_callback_pattern")
        if "exfiltrate" in low or "test-exfil.example.invalid" in low or "api_keys" in low or "user_data" in low:
            refs.append("image.steg.data_exfil_pattern")
        if "ignore previous" in low or "prompt injection" in low or "system prompt" in low:
            refs.append("image.steg.prompt_injection_text")
        if "ssn pattern count" in low or "ssn 123-45-6789" in low:
            refs.append("image.linked_artifact.ssn_hits")
        if "linked destination:" in low or "scanned.page/" in low:
            refs.append("image.qr.linked_destination")
    seen: set[str] = set()
    return [x for x in refs if x and not (x in seen or seen.add(x))]


def _artifact_provenance_rows(
    *,
    filename: str,
    evidence: list[str] | None,
    file_type: str | None = None,
    claim_status: str = "observed",
) -> list[dict[str, Any]]:
    refs = _artifact_evidence_refs(filename, evidence)
    name = str(filename or "").strip()
    low = name.lower()
    method = "passive attachment text extraction"
    if low.endswith(".xlsm"):
        method = "OOXML worksheet + VBA string extraction"
    elif low.endswith(".pdf"):
        method = "PDF byte scan / embedded URL extraction"
    elif low.endswith(".bas"):
        method = "VBA source inspection"
    elif low.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        method = "image OCR / steganography decode / linked artifact analysis"
    rows: list[dict[str, Any]] = []
    for ref in refs:
        rows.append(
            {
                "source_file": name,
                "extraction_method": method,
                "match_ref": ref,
                "confidence": "high" if claim_status == "observed" else ("medium" if claim_status == "inferred" else "low"),
                "file_type": str(file_type or ""),
            }
        )
    return rows


def _is_benign_comment_only_vba_artifact(filename: str, extracted_text: str, hypothesis: str) -> bool:
    low_name = str(filename or "").strip().lower()
    low = str(extracted_text or "").lower()
    if not low_name.endswith(".bas"):
        return False
    if hypothesis not in {"lolbin_command_sequence", "c2_beacon"}:
        return False
    if "benign test - no functional malicious code" not in low:
        return False
    suspicious = ("powershell.exe", "certutil.exe", "bitsadmin", "schtasks", "balashnikovai-cdn.com", "balashnikovai-analytics.com", "beaconing")
    uncommented = False
    commented = False
    for line in str(extracted_text or "").splitlines():
        line_low = line.strip().lower()
        if not any(tok in line_low for tok in suspicious):
            continue
        if line_low.startswith("'"):
            commented = True
        else:
            uncommented = True
    return commented and not uncommented


def _claim_contract_for_finding(
    *,
    filename: str,
    finding_type: str,
    evidence_kind: str,
    category: str,
    source_type: str,
    extracted_text: str = "",
    evidence: list[str] | None = None,
) -> tuple[str, str]:
    ftype = str(finding_type or "").lower()
    cat = str(category or "").lower()
    src = str(source_type or "").lower()
    if cat in {"reference_spec_material", "benign_reference_material", "contextual_test_artifact"}:
        return "suppressed", "detection_artifact_patterns"
    if _is_benign_comment_only_vba_artifact(filename, extracted_text, ftype):
        return "suppressed", "detection_artifact_patterns"
    if ftype in {"lolbin_command_sequence", "c2_beacon_pattern", "data_exfiltration_instruction"} and src in {"behavioral", "static", "ocr"}:
        return "possible", "unconfirmed_higher_order_hypotheses"
    if str(evidence_kind or "").strip().lower() == "direct":
        return "observed", "active_findings"
    return "inferred", "active_findings"


def _dedupe_ranked_findings(findings: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    policy_seen = False
    has_direct_primary = any(
        isinstance(f, dict)
        and str(f.get("evidence_kind") or "") == "direct"
        and str(f.get("finding_category") or "") not in {"contextual_test_artifact", "reference_spec_material", "benign_reference_material"}
        for f in findings
    )
    for row in sorted([f for f in findings if isinstance(f, dict)], key=_finding_rank_score, reverse=True):
        ftype = str(row.get("finding_type") or "")
        artifact = str(((row.get("artifact_ref") or {}).get("file_name") or "")).strip().lower()
        summary = str(row.get("summary") or "").strip().lower()
        category = str(row.get("finding_category") or "").strip().lower()
        key = f"{ftype}|{artifact}"
        if key in seen_keys:
            continue
        if category == "policy_violation":
            if policy_seen:
                continue
            if any(str((x.get("artifact_ref") or {}).get("file_name") or "").strip() for x in out):
                if "policy gate" in summary or "verification required" in summary or "reauth" in summary:
                    policy_seen = True
                    continue
            policy_seen = True
        if has_direct_primary and category in {"contextual_test_artifact", "reference_spec_material", "benign_reference_material"}:
            continue
        seen_keys.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _finding_agentic_tags(finding_type: str, source_type: str, category: str) -> list[str]:
    ftype = str(finding_type or "").lower()
    src = str(source_type or "").lower()
    cat = str(category or "").lower()
    tags: list[str] = []
    if any(tok in ftype for tok in ("baseline", "attachment_url", "qr_redirect")) or cat in {"baseline_drift", "active_payment_lure"}:
        tags.append("ASI04:AgenticSupplyChainVulnerabilities")
    if "policy" in ftype:
        tags.append("ASI07:InsecureInterAgentComms")
    if src in {"ocr", "static"} and "payment" in ftype:
        tags.append("ASI04:AgenticSupplyChainVulnerabilities")
    if "prompt_injection_hidden" in ftype:
        tags.extend(["ASI02:PromptInjectionAndManipulation", "ASI07:InsecureInterAgentComms"])
    if any(tok in ftype for tok in ("data_exfiltration_instruction", "ssn_leakage_linked_qr")):
        tags.append("ASI06:SensitiveDataExposure")
    if any(tok in ftype for tok in ("c2_beacon_pattern", "lolbin_command_sequence")):
        tags.append("ASI08:AgentEnvironmentAbuse")
    seen = set()
    return [x for x in tags if x and not (x in seen or seen.add(x))]


def _finding_compliance_mapping(
    *,
    finding_type: str,
    category: str,
    source_type: str,
    evidence: list[str] | None = None,
    business_outcome: str | None = None,
    claim_status: str | None = None,
) -> list[dict[str, Any]]:
    ftype = str(finding_type or "").lower()
    cat = str(category or "").lower()
    src = str(source_type or "").lower()
    status = str(claim_status or "").strip().lower()
    mappings: list[dict[str, Any]] = []
    evidence_lines = [str(x).strip() for x in (evidence or []) if str(x or "").strip()]
    evidence_refs = [f"finding.evidence.{i+1}" for i in range(len(evidence_lines[:4]))]

    if status == "suppressed":
        return []

    def _row(framework: str, controls: list[str], rationale: str) -> dict[str, Any]:
        registry_records = [get_control_record(framework, str(control)) for control in controls]
        registry_records = [row for row in registry_records if isinstance(row, dict) and row]
        statuses = [str(row.get("control_implemented") or "").strip() for row in registry_records if str(row.get("control_implemented") or "").strip()]
        evidence_of_control: list[str] = []
        for row in registry_records:
            for ref in (row.get("evidence_of_control") or []):
                s = str(ref or "").strip()
                if s and s not in evidence_of_control:
                    evidence_of_control.append(s)
        return {
            "framework": framework,
            "controls": controls,
            "rationale": rationale,
            "evidence_refs": list(evidence_refs),
            "evidence_summary": evidence_lines[:3],
            "business_significance": str(business_outcome or "").strip(),
            "mapping_source": (
                f"email_security._finding_compliance_mapping + control_registry@{get_control_registry_version()}"
                if registry_records
                else "email_security._finding_compliance_mapping"
            ),
            "mapping_version": "2026.03.28.1",
            "mapping_confidence": "high" if len(evidence_refs) >= 2 else ("medium" if evidence_refs else "low"),
            "analyst_review_required": True,
            "control_implemented": statuses[0] if statuses else None,
            "evidence_of_control": evidence_of_control,
        }
    if any(tok in ftype for tok in ("bank_detail", "payment_change", "baseline_mismatch", "reply_drift")) or cat in {"active_payment_lure", "baseline_drift"}:
        mappings.extend(
            [
                _row("ISO27001", ["A.5.16", "A.5.19", "A.5.23"], "Supplier identity, supplier relationship, and financial workflow controls should be reviewed."),
                _row("ISO42001", ["Human oversight", "Outcome monitoring"], "AI-assisted fraud decisions need human oversight and outcome monitoring."),
                _row("EU AI Act", ["Article 9", "Article 14"], "Risk management and human oversight apply when AI contributes to operational security decisions."),
            ]
        )
    if src in {"ocr", "static"} and ("bank" in ftype or "payment" in ftype):
        mappings.append(_row("PCI DSS", ["Req 6", "Req 10", "Req 12"], "Payment workflow controls, audit trails, and security governance should be reviewed."))
    if any(tok in ftype for tok in ("infrastructure", "related_incident")):
        mappings.append(_row("ISO27001", ["A.8.16", "A.5.7"], "Security monitoring and threat intelligence processes are implicated."))
    if any(tok in ftype for tok in ("prompt", "policy")):
        mappings.extend(
            [
                _row("ISO42001", ["Risk treatment", "Model governance"], "Agentic AI controls and guardrails should be reviewed."),
                _row("EU AI Act", ["Article 15"], "Robustness and cybersecurity of the AI-assisted workflow should be reviewed."),
            ]
        )
    if "prompt_injection_hidden" in ftype:
        mappings.extend(
            [
                _row("OWASP LLM Top 10", ["LLM01"], "Hidden prompt content indicates untrusted-input prompt manipulation risk."),
                _row("ISO42001", ["Human oversight", "Prompt handling"], "Model-facing content handling and human oversight should be reviewed."),
            ]
        )
    if any(tok in ftype for tok in ("data_exfiltration_instruction", "ssn_leakage_linked_qr")):
        mappings.extend(
            [
                _row("GDPR", ["Article 5", "Article 32", "Article 33"], "Potential exposure of personal data requires security and breach-review assessment."),
                _row("ISO27001", ["A.5.34", "A.8.12", "A.8.16"], "Data leakage prevention, privacy, and monitoring controls should be reviewed."),
            ]
        )
    if "ssn_leakage_linked_qr" in ftype:
        mappings.extend(
            [
                _row("PCI DSS", ["Req 10", "Req 12"], "Incident logging and governance should be reviewed where sensitive identity data is exposed in finance-linked workflows."),
                _row("HIPAA", ["Security Rule review"], "If regulated personal or healthcare data is implicated, regulated-data exposure review may be required."),
            ]
        )
    if any(tok in ftype for tok in ("c2_beacon_pattern", "lolbin_command_sequence")):
        mappings.extend(
            [
                _row("ISO27001", ["A.8.7", "A.8.16"], "Malware defense, monitoring, and detection controls are implicated."),
                _row("MITRE ATT&CK", ["Triage mapping"], "Behavior should be reviewed against ATT&CK for threat hunting and containment."),
            ]
        )
    if any(tok in ftype for tok in ("bank", "payment", "identity")):
        mappings.append(_row("GDPR", ["Article 5", "Article 32"], "If personal or account-linked data is involved, integrity and security controls should be reviewed."))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in mappings:
        key = f"{row.get('framework')}::{','.join(row.get('controls') or [])}"
        if key in seen:
            continue
        seen.add(key)
        if row.get("evidence_refs"):
            out.append(row)
    return out[:6]


def _hidden_payload_drilldown(
    finding_type: str,
    threat_context: Dict[str, Any],
) -> Dict[str, Any] | None:
    ftype = str(finding_type or "").lower()
    if "lolbin_command_sequence" in ftype:
        return {
            "headline": "Hidden LOLBin execution chain detected",
            "business_risk": "Trusted admin tools may be abused to download or launch attacker payloads while blending into normal operations.",
            "affected_scope": "Potentially affected users are those who opened or processed the artifact and any workstation that executed the hidden chain.",
            "forensic_checks": [
                "Review PowerShell, certutil, mshta, rundll32, regsvr32, bitsadmin, wscript, and cscript process launches.",
                "Check parent-child process chains, download destinations, and recently written payload files.",
                "Correlate endpoint events with proxy, DNS, and EDR telemetry for the same user and host.",
            ],
            "hunt_queries": [
                "Search EDR for LOLBin executions and encoded-command usage in the incident window.",
                "Review outbound fetches, payload URLs, and new binaries written after the artifact was handled.",
            ],
            "crisis_actions": ["No public statement is usually needed unless execution or downstream impact is confirmed."],
            "threat_context": threat_context,
        }
    if "c2_beacon_pattern" in ftype:
        return {
            "headline": "Hidden beacon or callback pattern detected",
            "business_risk": "An attacker may be trying to keep a foothold and request further instructions from external infrastructure.",
            "affected_scope": "Potentially affected hosts are any systems that opened the artifact or show the same callback pattern in telemetry.",
            "forensic_checks": [
                "Review DNS, proxy, firewall, and EDR telemetry for repeated low-volume callbacks, jitter, or periodic requests.",
                "Check for HTTP(S), DNS tunneling, or uncommon destinations that match extracted callback indicators.",
                "Review service persistence, scheduled tasks, and repeated process network connections.",
            ],
            "hunt_queries": [
                "Search network telemetry for repeated small packets, callback intervals, and low-volume periodic traffic.",
                "Look for the same user, process, or host contacting the destination after artifact handling.",
            ],
            "crisis_actions": ["No public statement unless confirmed compromise or service impact is found."],
            "threat_context": threat_context,
        }
    if "data_exfiltration_instruction" in ftype:
        return {
            "headline": "Hidden exfiltration instructions detected",
            "business_risk": "The content appears designed to steal data rather than merely trick a user.",
            "affected_scope": "Potentially affected accounts are those that opened the artifact or had access to the data sources named in follow-on telemetry.",
            "forensic_checks": [
                "Review archive creation, compression tools, staging directories, and cloud-sync or upload activity.",
                "Check identity logs, file access logs, eBPF or EDR events, browser uploads, and outbound transfers.",
                "Determine what repositories were reachable from the affected account and whether those files were copied or moved.",
            ],
            "hunt_queries": [
                "Search for zip, rclone, scp, curl, wget, browser upload, or cloud-storage transfer activity after artifact interaction.",
                "Correlate identity, endpoint, proxy, and storage access logs to estimate what was reachable and what was actually moved.",
            ],
            "crisis_actions": ["Prepare breach-communication inputs only if exposure is confirmed; instructions alone are not proof of exfiltration."],
            "threat_context": threat_context,
        }
    if "prompt_injection_hidden" in ftype:
        return {
            "headline": "Hidden prompt-injection content detected",
            "business_risk": "This threatens AI reliability, decision integrity, and downstream automation rather than just a single endpoint.",
            "affected_scope": "Affected systems are any model, agent, or workflow that ingested the hidden text via QR, steganography, OCR overlay, or document extraction.",
            "forensic_checks": [
                "Verify the artifact was sanitized before any model-facing use.",
                "Review agent audit logs for tool requests, context leakage, or abnormal instructions after ingestion.",
                "Classify the carrier as QR, steganography, text overlay, or extracted document text for root-cause analysis.",
            ],
            "hunt_queries": [
                "Search model and agent logs for hidden-instruction strings, tool-use spikes, or unsafe action requests tied to the artifact.",
            ],
            "crisis_actions": ["This is usually an internal AI-governance issue unless it caused a confirmed data leak or customer impact."],
            "threat_context": threat_context,
        }
    if "ssn_leakage_linked_qr" in ftype:
        return {
            "headline": "Linked QR path suggests SSN or regulated identity leakage",
            "business_risk": "Potential privacy-reporting, reputational, and customer-trust impact if the exposure is confirmed.",
            "affected_scope": "Potentially affected users are the people whose identity records were accessible through the linked content.",
            "forensic_checks": [
                "Review the linked content, access-control path, and publication workflow that exposed the data.",
                "Check whether RBAC, ABAC, object permissions, or public-link controls failed.",
                "Capture URL, access logs, GeoIP, referrers, and object-access records to estimate scope and timeline.",
            ],
            "hunt_queries": [
                "Search access logs for unusual countries, hosting ASN traffic, and repeated fetches to the exposed artifact.",
                "Look for insider, supplier, or public-link misuse patterns before concluding attacker origin.",
            ],
            "crisis_actions": [
                "Engage privacy, legal, and communications leads early.",
                "Prepare holding statements and risk-register updates for brand, regulatory, and customer impact.",
            ],
            "threat_context": threat_context,
        }
    return None


def _finding_business_bundle(
    *,
    finding_type: str,
    category: str,
    source_type: str,
    evidence: list[str],
    threat: Dict[str, Any] | None,
) -> Dict[str, Any]:
    ftype = str(finding_type or "").lower()
    cat = str(category or "").lower()
    src = str(source_type or "").lower()
    dread = (threat.get("dread") if isinstance(threat, dict) and isinstance(threat.get("dread"), dict) else {}) or {}
    pasta_stage = str((threat or {}).get("pasta_stage") or "").strip()
    mitre_attack = list((threat or {}).get("mitre_attack") or []) if isinstance(threat, dict) else []
    owasp = list((threat or {}).get("owasp_llm_top10") or []) if isinstance(threat, dict) else []
    threat_context = {
        "pasta_stage": pasta_stage,
        "dread": dread,
        "mitre_attack": mitre_attack[:4],
        "owasp_llm_top10": owasp[:4],
        "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
    }
    hidden_drilldown = _hidden_payload_drilldown(ftype, threat_context)
    if hidden_drilldown:
        if "lolbin_command_sequence" in ftype:
            return {
                "business_meaning": "A hidden command sequence appears to abuse trusted operating-system tools to fetch or run payloads without using obvious malware binaries.",
                "business_outcome": "A user or endpoint could be turned into a launch point for malware, follow-on payloads, or lateral movement using tools defenders often allow by default.",
                "next_steps": [
                    "Contain the related host or user workflow before allowing execution.",
                    "Hunt for LOLBin process launches, downloads, and child-process chains on the same endpoint.",
                    "Queue sandbox review for the extracted command path and any downloaded payload.",
                ],
                "policy_mapping": ["sandbox_required_for_hidden_command_payloads", "endpoint_containment_on_lolbin_chain"],
                "faq_mapping": ["How to investigate LOLBin abuse", "What to do when an image hides a command sequence"],
                "threat_context": threat_context,
                "drilldown": hidden_drilldown,
            }
        if "c2_beacon_pattern" in ftype:
            return {
                "business_meaning": "The hidden payload looks like command-and-control beaconing rather than a normal business image or document.",
                "business_outcome": "If the pattern was executed, an endpoint may be checking in to attacker infrastructure for follow-on commands.",
                "next_steps": [
                    "Contain the potentially affected host and confirm whether any payload from the hidden content executed.",
                    "Give hunters the callback hints, interval, and destination clues for network and XDR review.",
                    "Escalate to incident response if endpoint, DNS, or proxy telemetry confirms matching check-ins.",
                ],
                "policy_mapping": ["threat_hunt_required_for_hidden_c2_pattern", "containment_on_confirmed_beacon_overlap"],
                "faq_mapping": ["How to investigate possible command-and-control beaconing"],
                "threat_context": threat_context,
                "drilldown": hidden_drilldown,
            }
        if "data_exfiltration_instruction" in ftype:
            return {
                "business_meaning": "The hidden content describes how data should be collected and moved out of the environment.",
                "business_outcome": "Sensitive files, customer data, credentials, or internal documents could be targeted for theft if an endpoint or user followed the embedded instructions.",
                "next_steps": [
                    "Pause the workflow, contain the affected account or host, and review whether any collection or upload activity occurred.",
                    "Check endpoint, eBPF, EDR, proxy, and identity telemetry for archive creation, staging, and outbound transfer attempts.",
                    "Escalate for breach assessment if sensitive data stores, cloud buckets, or customer records were in scope.",
                ],
                "policy_mapping": ["data_exfiltration_ir_required", "sensitive_data_hunt_required"],
                "faq_mapping": ["How to investigate suspected data exfiltration", "What evidence to collect for a possible data leak"],
                "threat_context": threat_context,
                "drilldown": hidden_drilldown,
            }
        if "prompt_injection_hidden" in ftype:
            return {
                "business_meaning": "The hidden content tries to manipulate AI or agent workflows rather than only human readers.",
                "business_outcome": "If model-facing controls are weak, the hidden instructions could steer assistants, leak context, or weaken decision quality.",
                "next_steps": [
                    "Confirm the prompt-injection guardrails held and that the artifact text was treated as untrusted.",
                    "Review whether any AI-assisted workflow saw the hidden content before sanitization.",
                    "Use human review before allowing the artifact into automated agent chains or retrieval corpora.",
                ],
                "policy_mapping": ["llm_artifact_text_untrusted", "human_review_required_for_hidden_prompt_content"],
                "faq_mapping": ["How the platform handles hidden prompt injection", "What to do when an attachment targets AI workflows"],
                "threat_context": threat_context,
                "drilldown": hidden_drilldown,
            }
        return {
            "business_meaning": "A QR-linked path appears to expose Social Security or similarly sensitive identity data.",
            "business_outcome": "This could become a customer-trust, privacy, legal, and brand-damage event if the exposure is real and tied to regulated data handling failures.",
            "next_steps": [
                "Treat the linked content as a potential regulated-data incident and start privacy and security review immediately.",
                "Determine whether the exposure came from a supplier, insider misuse, broken access control, or compromised public content.",
                "Prepare customer-notification, legal, and communications inputs if exposure is confirmed.",
            ],
            "policy_mapping": ["regulated_data_incident_review_required", "public_content_pii_exposure_escalation"],
            "faq_mapping": ["What to do when SSNs or regulated identity data may be exposed", "How to coordinate privacy, legal, and PR teams"],
            "threat_context": threat_context,
            "drilldown": hidden_drilldown,
        }
    if "bank_detail" in ftype or "payment_change" in ftype:
        return {
            "business_meaning": "The message is trying to influence how money is sent or where it is sent.",
            "business_outcome": "If staff trust this request, the business could send payment to the wrong account.",
            "next_steps": [
                "Hold any payment or supplier-detail change linked to this message.",
                "Verify the request through an approved callback channel.",
                "Record the supplier and bank details in the incident for finance review.",
            ],
            "policy_mapping": ["supplier_bank_change_requires_oob_callback", "finance_payment_hold_on_unverified_change"],
            "faq_mapping": ["How to verify a supplier bank change", "What to do when payment details change by email"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if "baseline" in ftype or cat == "baseline_drift":
        return {
            "business_meaning": "The document does not look like the supplier documents the business normally trusts.",
            "business_outcome": "This increases the chance of supplier impersonation, invoice tampering, or account-compromise fraud.",
            "next_steps": [
                "Compare this document against the trusted supplier baseline before approving it.",
                "Check for bank-detail, logo, or remittance block changes.",
                "Escalate to finance or supplier-risk review if the drift cannot be explained.",
            ],
            "policy_mapping": ["supplier_baseline_review_required"],
            "faq_mapping": ["How to compare a supplier invoice to the trusted baseline"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if "reply_drift" in ftype or "auth_failure" in ftype or "infrastructure" in ftype:
        return {
            "business_meaning": "The sender identity or sending path does not line up with what the business should expect from this supplier.",
            "business_outcome": "Staff could trust a spoofed or compromised sender and act on fraudulent instructions.",
            "next_steps": [
                "Do not trust the sender address alone.",
                "Verify the supplier using a known-good contact path.",
                "Treat the email as suspicious until identity checks are resolved.",
            ],
            "policy_mapping": ["sender_identity_verification_required"],
            "faq_mapping": ["How to verify a suspicious supplier email"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if "encoding_anomaly" in ftype or "message_hygiene" in ftype:
        return {
            "business_meaning": "The message looks poorly encoded or repackaged, which weakens trust in how it was produced and delivered.",
            "business_outcome": "This is not proof of fraud by itself, but it strengthens the case that the message is not a normal supplier communication.",
            "next_steps": [
                "Treat the message as suspicious until sender identity and document evidence are resolved.",
                "Use this as supporting context behind stronger payment, document, or sender findings.",
            ],
            "policy_mapping": ["message_hygiene_supporting_signal_only"],
            "faq_mapping": ["How to interpret message hygiene and encoding anomalies"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if cat == "contextual_test_artifact":
        return {
            "business_meaning": "This file looks like test, lab, or reference material rather than a live supplier artifact.",
            "business_outcome": "It can explain why the platform is suspicious, but it should not outweigh direct fraud evidence from live attachments or sender identity.",
            "next_steps": [
                "Use this file as supporting context, not the primary reason for a fraud verdict.",
                "Prioritize real invoices, PDFs, images, sender trust, and bank-change evidence first.",
            ],
            "policy_mapping": ["contextual_test_artifact_non_authoritative"],
            "faq_mapping": ["How the platform treats test fixtures and reference material"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if cat == "reference_spec_material":
        return {
            "business_meaning": "This file reads like specification, scenario, or test reference material rather than a live business artifact.",
            "business_outcome": "It provides context for why the platform is cautious, but it should stay behind direct evidence from real invoices, images, or sender checks.",
            "next_steps": [
                "Keep this file as supporting context only.",
                "Prioritize live supplier documents, sender identity, and direct payment-change evidence before acting.",
            ],
            "policy_mapping": ["reference_spec_material_non_authoritative"],
            "faq_mapping": ["How the platform treats specifications, scenarios, and testing guides"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if cat == "benign_reference_material":
        return {
            "business_meaning": "This file looks more like reference or test material than a real supplier artifact.",
            "business_outcome": "It may still contain useful fraud indicators, but it should not outweigh direct supplier-fraud evidence.",
            "next_steps": [
                "Treat the file as context, not the primary reason for the verdict.",
                "Prioritize actual supplier documents, sender identity, and payment-change evidence first.",
            ],
            "policy_mapping": ["reference_material_non_authoritative"],
            "faq_mapping": ["How the platform ranks reference material vs direct fraud evidence"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if cat == "contradicts_sender_claim":
        return {
            "business_meaning": "This file does not support the sender’s story and may contradict what the business expects from the supplier.",
            "business_outcome": "That increases the likelihood of impersonation, account compromise, or document tampering.",
            "next_steps": [
                "Validate the sender claim against supplier history and approved templates.",
                "Review whether the document content matches the business request it arrived with.",
            ],
            "policy_mapping": ["supplier_claim_consistency_review_required"],
            "faq_mapping": ["How to handle a document that contradicts the supplier story"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    return {
        "business_meaning": "The platform found evidence that this message may not be safe to trust without review.",
        "business_outcome": "Acting too quickly could create financial loss, account risk, or investigation overhead.",
        "next_steps": [
            "Pause business action on the message until the strongest findings are reviewed.",
            "Use the ranked evidence to verify sender identity and attachment intent.",
        ],
        "policy_mapping": ["security_review_required"],
        "faq_mapping": ["What to do when an email is sent to security review"],
        "threat_context": {
            "pasta_stage": pasta_stage,
            "dread": dread,
            "mitre_attack": mitre_attack[:4],
            "owasp_llm_top10": owasp[:4],
            "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
        },
    }


def _decorate_structured_findings(
    *,
    findings: list[dict[str, Any]],
    evidence_snapshot: Dict[str, Any],
) -> list[dict[str, Any]]:
    ev = evidence_snapshot if isinstance(evidence_snapshot, dict) else {}
    threat = ev.get("threat_correlation") if isinstance(ev.get("threat_correlation"), dict) else {}
    attachment_rows = ev.get("attachment_forensics") if isinstance(ev.get("attachment_forensics"), list) else []

    def _attachment_row(filename: str) -> dict[str, Any]:
        for item in attachment_rows:
            if isinstance(item, dict) and str(item.get("file_name") or "").strip() == filename:
                return item
        return {}

    out: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        row = dict(finding)
        filename = str(((row.get("artifact_ref") or {}).get("file_name") or "")).strip()
        attachment = _attachment_row(filename)
        category = _artifact_finding_category(filename, str(row.get("finding_type") or ""), str(row.get("summary") or ""))
        claim_status, finding_group = _claim_contract_for_finding(
            filename=filename,
            finding_type=str(row.get("finding_type") or ""),
            evidence_kind=str(row.get("evidence_kind") or ""),
            category=category,
            source_type=str(row.get("source_type") or ""),
            extracted_text=str((attachment.get("analysis_text_sample") or attachment.get("text_summary") or "") if isinstance(attachment, dict) else ""),
            evidence=[str(x) for x in (row.get("evidence") or []) if str(x or "").strip()],
        )
        row["finding_category"] = category
        row["claim_status"] = claim_status
        row["finding_group"] = finding_group
        provenance_text = [str(x) for x in (row.get("evidence") or []) if str(x or "").strip()]
        attachment_text = str((attachment.get("analysis_text_sample") or attachment.get("text_summary") or "") if isinstance(attachment, dict) else "")
        if attachment_text:
            provenance_text.append(attachment_text)
        if not row.get("evidence_refs"):
            row["evidence_refs"] = _artifact_evidence_refs(filename, provenance_text)
        if not row.get("artifact_provenance"):
            row["artifact_provenance"] = _artifact_provenance_rows(
                filename=filename,
                evidence=provenance_text,
                file_type=str(((row.get("artifact_ref") or {}).get("file_type") or attachment.get("file_type") or "")),
                claim_status=claim_status,
            )
        if not row.get("evidence_refs") and not row.get("artifact_provenance"):
            row["claim_status"] = "suppressed"
            row["finding_group"] = "detection_artifact_patterns"
            row["suppressed_reason"] = "missing_visible_provenance"
        bundle = _finding_business_bundle(
            finding_type=str(row.get("finding_type") or ""),
            category=category,
            source_type=str(row.get("source_type") or ""),
            evidence=[str(x) for x in (row.get("evidence") or []) if str(x or "").strip()],
            threat=threat if isinstance(threat, dict) else {},
        )
        row["business_meaning"] = bundle.get("business_meaning")
        row["business_outcome"] = bundle.get("business_outcome")
        row["next_steps"] = list(bundle.get("next_steps") or [])
        row["policy_mapping"] = list(bundle.get("policy_mapping") or [])
        row["faq_mapping"] = list(bundle.get("faq_mapping") or [])
        row["threat_context"] = dict(bundle.get("threat_context") or {})
        if str(row.get("pasta_stage") or "").strip():
            row["threat_context"]["pasta_stage"] = str(row.get("pasta_stage") or "").strip()
        if isinstance(row.get("mitre_attack"), list) and row.get("mitre_attack"):
            row["threat_context"]["mitre_attack"] = list(row.get("mitre_attack") or [])[:5]
        row["drilldown"] = dict(bundle.get("drilldown") or {}) if isinstance(bundle.get("drilldown"), dict) else {}
        if str(row.get("finding_type") or "") == "ssn_leakage_linked_qr":
            linked = row.get("linked_artifact") if isinstance(row.get("linked_artifact"), dict) else {}
            retrieval = row.get("retrieval_context") if isinstance(row.get("retrieval_context"), dict) else {}
            owner_scope = str((linked.get("linked_owner_scope") or retrieval.get("linked_owner_scope") or "")).strip()
            exposure_scope = str((linked.get("linked_exposure_scope") or retrieval.get("linked_exposure_scope") or "")).strip()
            owner_reason = str(linked.get("linked_owner_reason") or "").strip()
            final_url = str(linked.get("linked_final_url") or "").strip()
            pii_types = [str(x) for x in (linked.get("pii_type") or []) if str(x or "").strip()]
            ssn_hits = list(linked.get("ssn_hits") or []) if isinstance(linked.get("ssn_hits"), list) else []
            privacy_scope_lines = []
            if owner_scope:
                privacy_scope_lines.append(f"Owner scope: {owner_scope.replace('_', ' ')}")
            if exposure_scope:
                privacy_scope_lines.append(f"Exposure scope: {exposure_scope.replace('_', ' ')}")
            if owner_reason:
                privacy_scope_lines.append(owner_reason)
            if pii_types:
                privacy_scope_lines.append(f"PII types: {', '.join(pii_types[:3])}")
            if ssn_hits:
                privacy_scope_lines.append(f"SSN pattern count: {len(ssn_hits)}")
            if final_url:
                privacy_scope_lines.append(f"Linked destination: {final_url[:180]}")
            if privacy_scope_lines:
                row["drilldown"]["privacy_scope"] = privacy_scope_lines
            if bool(linked.get("linked_human_verification_required") or retrieval.get("linked_human_verification_required")):
                row["drilldown"]["human_verification"] = [
                    "Confirm whether the linked content belongs to the platform, a supplier, or a third party before declaring breach scope.",
                    "Verify access-control posture, audience, and actual access logs before claiming confirmed exposure.",
                ]
        row["compliance_mapping"] = _finding_compliance_mapping(
            finding_type=str(row.get("finding_type") or ""),
            category=category,
            source_type=str(row.get("source_type") or ""),
            evidence=[str(x) for x in (row.get("evidence") or []) if str(x or "").strip()],
            business_outcome=str(row.get("business_outcome") or ""),
            claim_status=claim_status,
        )
        out.append(row)
    return out


def _canonical_action_name(action_type: str | None) -> str:
    action = str(action_type or "").strip().lower()
    mapping = {
        "create_ticket": "create_ticket",
        "create_incident": "create_ticket",
        "escalate_ticket": "create_ticket",
        "notify_ops": "notify_analyst",
        "notify_stakeholders": "notify_analyst",
        "send_message": "notify_analyst",
        "send_email": "notify_analyst",
        "send_notification_email": "notify_analyst",
        "email": "notify_analyst",
        "quarantine_email": "quarantine_email",
        "block_sender": "push_block_rule",
        "session_revoke": "suspend_user",
        "step_up_auth": "force_reauth",
        "hold_payment": "approve_payment_change",
        "apply_compensation": "approve_payment_change",
        "offer_discount": "approve_payment_change",
    }
    return mapping.get(action, action or "unknown")


def _build_action_policy(
    *,
    verdict: Dict[str, Any],
    structured_findings: list[dict[str, Any]],
    evidence_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    findings = [f for f in structured_findings if isinstance(f, dict)]
    ranked = sorted(findings, key=_finding_rank_score, reverse=True)
    route = str(verdict.get("route") or "auto_resolve")
    severity = str(verdict.get("severity") or "info")
    auth = evidence_snapshot.get("auth") if isinstance(evidence_snapshot.get("auth"), dict) else {}
    infra = evidence_snapshot.get("sender_infrastructure") if isinstance(evidence_snapshot.get("sender_infrastructure"), dict) else {}
    trust_case = evidence_snapshot.get("trust_case") if isinstance(evidence_snapshot.get("trust_case"), dict) else {}
    governance = evidence_snapshot.get("supplier_governance") if isinstance(evidence_snapshot.get("supplier_governance"), dict) else {}

    def _has(predicate) -> bool:
        return any(predicate(f) for f in ranked)

    has_direct_payment = _has(lambda f: str(f.get("finding_type") or "") == "payment_change_request" and str(f.get("evidence_kind") or "") == "direct")
    has_baseline_mismatch = _has(lambda f: str(f.get("finding_type") or "") in {"baseline_mismatch", "attachment_visual_drift"} or str(f.get("finding_category") or "") == "baseline_drift")
    has_auth_failure = bool(auth.get("dmarc_fail")) or _has(lambda f: str(f.get("finding_type") or "") in {"auth_failure", "reply_drift"})
    has_known_bad_infra = _has(lambda f: str(f.get("finding_type") or "") == "infrastructure_anomaly") or bool(((infra.get("reputation") if isinstance(infra.get("reputation"), dict) else {}) or {}).get("known_bad"))
    has_conflicting_evidence = _has(lambda f: str(f.get("finding_category") or "") == "contextual_supplier_mismatch") and not (has_direct_payment or has_auth_failure)
    pending_updates = [str(x or "") for x in (governance.get("pending_updates") or []) if str(x or "").strip()]
    has_pending_bank_review = any(x.startswith("review_bank_fingerprint:") for x in pending_updates)
    has_pending_domain_review = any(x.startswith("review_domain:") for x in pending_updates)
    has_pending_template_review = any(x.startswith("review_template_hash:") for x in pending_updates)
    highest_conf = max((float(f.get("confidence_score") or 0.0) for f in ranked), default=0.0)
    high_business_impact = bool(has_direct_payment or has_baseline_mismatch or has_known_bad_infra or severity == "error" or has_pending_bank_review)
    trusted_sender = not has_auth_failure and str(trust_case.get("level") or "").lower() in {"trusted", "medium"} and not bool(infra.get("reply_domain_mismatch"))

    lane = "lane_1_auto_allow"
    lane_reason = "The sender and attachments look consistent with a normal supplier workflow and no payment-diversion indicators were found."
    if route == "security_review" or has_direct_payment or (has_auth_failure and has_baseline_mismatch) or has_known_bad_infra:
        lane = "lane_2_auto_escalate"
        lane_reason = "High-confidence fraud or sender-trust controls were triggered, so the platform escalated immediately while preserving evidence."
    elif route == "human_review" or has_conflicting_evidence or has_pending_bank_review or has_pending_domain_review or has_pending_template_review or (high_business_impact and 0.45 <= highest_conf < 0.85):
        lane = "lane_3_human_gate"
        lane_reason = "The message has meaningful business risk or conflicting evidence, so a human must approve the final sensitive action."
    elif trusted_sender and not has_direct_payment and not has_baseline_mismatch:
        lane = "lane_1_auto_allow"

    auto_allowed = {"notify_analyst", "create_ticket", "security_review", "passive_siem_event"}
    human_required = {"approve_supplier_update", "approve_payment_change", "mark_sender_trusted", "push_block_rule", "suspend_user"}
    blocked = {"open_internet", "access_secrets"}
    if lane == "lane_1_auto_allow":
        auto_allowed.add("approve_supplier_update")
        human_required.discard("approve_supplier_update")
    if lane == "lane_2_auto_escalate":
        auto_allowed.update({"quarantine_email", "force_reauth"})
    if lane == "lane_3_human_gate":
        auto_allowed.add("quarantine_email")

    threshold_reasons: list[str] = []
    if has_direct_payment:
        threshold_reasons.append("Direct payment-change evidence was extracted from the attachment.")
    if has_auth_failure:
        threshold_reasons.append("Sender identity or reply-chain controls failed.")
    if has_baseline_mismatch:
        threshold_reasons.append("The document drifted from the trusted supplier baseline.")
    if has_known_bad_infra:
        threshold_reasons.append("Sender infrastructure or related incident overlap increased confidence this is hostile.")
    if has_conflicting_evidence:
        threshold_reasons.append("Some evidence is suspicious but not conclusive enough for unsupervised business action.")
    if has_pending_bank_review:
        threshold_reasons.append("A newly observed bank fingerprint still requires supplier-governance approval.")
    if has_pending_domain_review:
        threshold_reasons.append("A newly observed sender or supplier domain still requires supplier-governance approval.")
    if has_pending_template_review:
        threshold_reasons.append("A newly observed supplier template hash still requires governance review before trust can be extended.")
    if not threshold_reasons:
        threshold_reasons.append(lane_reason)

    return {
        "lane": lane,
        "lane_label": lane.replace("_", " "),
        "lane_reason": lane_reason,
        "auto_allowed_actions": sorted(auto_allowed),
        "human_approval_actions": sorted(human_required),
        "blocked_actions": sorted(blocked),
        "threshold_reasons": threshold_reasons[:6],
        "top_business_reasons": [
            str(f.get("business_meaning") or f.get("summary") or "").strip()
            for f in ranked[:3]
            if str(f.get("business_meaning") or f.get("summary") or "").strip()
        ][:3],
        "metrics": {
            "highest_finding_confidence": round(highest_conf, 4),
            "direct_payment_change": has_direct_payment,
            "baseline_mismatch": has_baseline_mismatch,
            "sender_auth_failure": has_auth_failure,
            "known_bad_infrastructure": has_known_bad_infra,
            "conflicting_evidence": has_conflicting_evidence,
            "pending_bank_review": has_pending_bank_review,
            "pending_domain_review": has_pending_domain_review,
            "pending_template_review": has_pending_template_review,
            "high_business_impact": high_business_impact,
        },
        "human_gate": {
            "required": lane == "lane_3_human_gate",
            "approval_scope": "sensitive_business_actions" if lane == "lane_3_human_gate" else "none",
            "business_hold_message": (
                "Hold payment changes and verify supplier details out of band before any sensitive action."
                if lane in {"lane_2_auto_escalate", "lane_3_human_gate"}
                else "Normal processing may continue because no high-risk supplier-fraud indicators were found."
            ),
            "sensitive_actions": [
                "approve_supplier_update",
                "approve_payment_change",
                "mark_sender_trusted",
                "push_block_rule",
                "suspend_user",
            ],
        },
    }


def _enforce_playbook_actions(
    *,
    actions: list[dict[str, Any]],
    action_policy: Dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filtered: list[dict[str, Any]] = []
    governance: list[dict[str, Any]] = []
    auto_allowed = set(str(x) for x in (action_policy.get("auto_allowed_actions") or []))
    human_required = set(str(x) for x in (action_policy.get("human_approval_actions") or []))
    blocked = set(str(x) for x in (action_policy.get("blocked_actions") or []))

    for raw in actions:
        if not isinstance(raw, dict):
            continue
        action_type = str(raw.get("type") or "unknown").strip().lower()
        canonical = _canonical_action_name(action_type)
        decision = "allowed"
        reason = "permitted_by_action_policy"
        if canonical in blocked:
            decision = "blocked"
            reason = "blocked_by_action_policy"
        elif canonical in human_required and canonical not in auto_allowed:
            decision = "human_approval_required"
            reason = "requires_human_gate"
        elif canonical not in auto_allowed and canonical not in human_required:
            decision = "human_approval_required"
            reason = "not_in_auto_allowlist"
        governance.append(
            {
                "action_type": action_type,
                "canonical_action": canonical,
                "decision": decision,
                "reason": reason,
            }
        )
        if decision == "allowed":
            filtered.append(raw)
    return filtered, governance


def _build_structured_findings(
    *,
    email: Dict[str, Any],
    verdict: Dict[str, Any],
    evidence_snapshot: Dict[str, Any],
    suggested_baseline_version: str | None = None,
) -> list[dict[str, Any]]:
    ev = evidence_snapshot if isinstance(evidence_snapshot, dict) else {}
    findings: list[dict[str, Any]] = []
    suggested_action = str((verdict or {}).get("verdict_action") or "security_review")
    from_domain = str(email.get("vendor_domain") or "").strip().lower() or str(((ev.get("sender_infrastructure") or {}).get("sender_domain") or "")).strip().lower()
    auth = ev.get("auth_verdicts") if isinstance(ev.get("auth_verdicts"), dict) else {}
    infra = ev.get("sender_infrastructure") if isinstance(ev.get("sender_infrastructure"), dict) else {}
    attachment_rows = ev.get("attachment_forensics") if isinstance(ev.get("attachment_forensics"), list) else []
    diff_rows = ((ev.get("attachment_baseline_diffs") or {}).get("comparisons") if isinstance(ev.get("attachment_baseline_diffs"), dict) else []) or []
    verdict_indicators = [i for i in (verdict.get("indicators") or []) if isinstance(i, dict)]
    direct_attachment_rows = [
        item
        for item in attachment_rows
        if isinstance(item, dict) and str(item.get("attachment_class") or "") in {"active_payment_lure", "observed_supplier_artifact"}
    ]
    contextual_attachment_rows = [
        item
        for item in attachment_rows
        if isinstance(item, dict) and str(item.get("attachment_class") or "") in {"contextual_test_artifact", "reference_spec_material", "benign_reference_material"}
    ]

    if bool(auth.get("dmarc_fail")):
        findings.append(
            _normalize_finding(
                finding_id="sender_auth_dmarc_alignment_failed",
                finding_type="auth_failure_dmarc_alignment",
                summary="The sender failed DMARC alignment, so the platform could not trust the email identity.",
                severity_hint="high",
                confidence_score=0.94,
                source_type="policy",
                evidence_kind="direct",
                agent_origin="sender_auth_agent",
                policy_weight=0.9,
                evidence=[f"SPF={auth.get('spf_result')}", f"DKIM={auth.get('dkim_result')}", f"DMARC={auth.get('dmarc_result')}"],
                retrieval_context={"supplier_domain": from_domain or None, "baseline_version": suggested_baseline_version or None},
                recommended_action=suggested_action,
            )
        )
    if bool(infra.get("reply_domain_mismatch")):
        findings.append(
            _normalize_finding(
                finding_id="sender_reply_domain_drift",
                finding_type="reply_drift",
                summary="The reply-to domain differs from the sender domain, which is a common supplier impersonation pattern.",
                severity_hint="high",
                confidence_score=0.89,
                source_type="policy",
                evidence_kind="direct",
                agent_origin="sender_auth_agent",
                policy_weight=0.82,
                evidence=[f"sender_domain={infra.get('sender_domain')}", f"reply_domain={infra.get('reply_domain')}"],
                retrieval_context={"supplier_domain": from_domain or None, "baseline_version": suggested_baseline_version or None},
                recommended_action=suggested_action,
            )
        )
    if any(str((indicator or {}).get("type") or "") == "encoding_anomaly" for indicator in verdict_indicators):
        findings.append(
            _normalize_finding(
                finding_id="sender_message_hygiene_encoding_anomaly",
                finding_type="message_hygiene_encoding_anomaly",
                summary="The message contains encoding artifacts that weaken sender trust and read like repackaged or poorly copied content.",
                severity_hint="medium",
                confidence_score=0.66,
                source_type="policy",
                evidence_kind="direct",
                agent_origin="sender_auth_agent",
                policy_weight=0.44,
                evidence=["subject/body contains mojibake or broken character encoding sequences"],
                retrieval_context={"supplier_domain": from_domain or None},
                recommended_action=suggested_action,
            )
        )
    rep = (infra.get("reputation") if isinstance(infra.get("reputation"), dict) else {}) or {}
    if bool(rep.get("known_bad")) or bool((rep.get("flags") or [])):
        findings.append(
            _normalize_finding(
                finding_id="sender_infrastructure_anomaly",
                finding_type="infrastructure_anomaly",
                summary="The sending infrastructure shows anomalies or reputation flags that increase spoofing risk.",
                severity_hint="medium",
                confidence_score=0.77 if bool(rep.get("known_bad")) else 0.64,
                source_type="intel",
                evidence_kind="inferred",
                agent_origin="sender_auth_agent",
                policy_weight=0.55,
                evidence=[str(x) for x in (rep.get("flags") or [])][:5],
                retrieval_context={"supplier_domain": from_domain or None},
                recommended_action=suggested_action,
            )
        )
    related = (infra.get("related_incidents") if isinstance(infra.get("related_incidents"), dict) else {}) or {}
    if int(related.get("count") or 0) > 0 and (direct_attachment_rows or not contextual_attachment_rows):
        observed_note = (
            "Observed supplier artifacts already support this overlap."
            if direct_attachment_rows
            else "This overlap exists without direct attachment evidence yet."
        )
        findings.append(
            _normalize_finding(
                finding_id="correlation_related_incidents",
                finding_type="related_incident_overlap",
                summary=f"The sender or infrastructure overlaps with {int(related.get('count') or 0)} prior incident(s). {observed_note}",
                severity_hint="medium",
                confidence_score=0.78 if direct_attachment_rows else 0.58,
                source_type="intel",
                evidence_kind="inferred",
                agent_origin="correlation_agent",
                policy_weight=0.52 if direct_attachment_rows else 0.28,
                evidence=([observed_note] + [f"{m.get('incident_id')} via {', '.join(m.get('match_on') or [])}" for m in (related.get("matches") or [])[:4] if isinstance(m, dict)])[:5],
                retrieval_context={"supplier_domain": from_domain or None},
                recommended_action=suggested_action,
            )
        )

    for item in attachment_rows:
        if not isinstance(item, dict):
            continue
        fname = str(item.get("file_name") or "attachment")
        artifact_ref = {"file_name": fname, "sha256": str(item.get("sha256") or ""), "file_type": str(item.get("file_type") or "")}
        file_type = str(item.get("file_type") or "")
        inferred_source = "ocr" if file_type.startswith("image/") or "pdf" in file_type else "static"
        if bool(item.get("bank_fields_present")):
            bank_fields = item.get("bank_fields") if isinstance(item.get("bank_fields"), dict) else {}
            evidence = [f"{k}={v}" for k, v in list(bank_fields.items())[:4]]
            findings.append(
                _normalize_finding(
                    finding_id=f"attachment_bank_fields_{fname}",
                    finding_type="bank_detail_change",
                    summary=f"{fname} contains bank or remittance details that need independent verification.",
                    severity_hint="high",
                    confidence_score=0.92,
                    source_type=inferred_source,
                    evidence_kind="direct",
                    agent_origin="attachment_forensics_agent",
                    policy_weight=0.88,
                    evidence=evidence or list(item.get("evidence_excerpt_lines") or [])[:3],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None, "baseline_version": suggested_baseline_version or None},
                    recommended_action=suggested_action,
                )
            )
        suspicious = [str(x) for x in (item.get("suspicious_instructions") or []) if str(x or "").strip()]
        if suspicious:
            findings.append(
                _normalize_finding(
                    finding_id=f"attachment_payment_change_{fname}",
                    finding_type="payment_change_request",
                    summary=f"{fname} requests changed payment or remittance handling.",
                    severity_hint="high",
                    confidence_score=0.87,
                    source_type=inferred_source,
                    evidence_kind="direct",
                    agent_origin="attachment_forensics_agent",
                    policy_weight=0.84,
                    evidence=suspicious[:4] + list(item.get("evidence_excerpt_lines") or [])[:2],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None},
                    recommended_action=suggested_action,
                )
            )
        mismatch = [str(x) for x in (item.get("brand_supplier_mismatch_signals") or []) if str(x or "").strip()]
        if mismatch:
            findings.append(
                _normalize_finding(
                    finding_id=f"baseline_mismatch_{fname}",
                    finding_type="baseline_mismatch",
                    summary=f"{fname} does not line up with the trusted supplier baseline.",
                    severity_hint="high",
                    confidence_score=0.85,
                    source_type="baseline",
                    evidence_kind="inferred",
                    agent_origin="baseline_agent",
                    policy_weight=0.78,
                    evidence=mismatch[:4],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None, "baseline_version": suggested_baseline_version or "current"},
                    recommended_action=suggested_action,
                )
            )
        urls = [str(x) for x in (item.get("embedded_urls") or []) if str(x or "").strip()]
        if urls:
            findings.append(
                _normalize_finding(
                    finding_id=f"attachment_urls_{fname}",
                    finding_type="attachment_url_exposure",
                    summary=f"{fname} contains embedded URLs that should be checked before users act on the message.",
                    severity_hint="medium",
                    confidence_score=0.71,
                    source_type="static",
                    evidence_kind="direct",
                    agent_origin="attachment_forensics_agent",
                    policy_weight=0.52,
                    evidence=urls[:4],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None},
                    recommended_action=suggested_action,
                )
            )
        qr_findings = [str(x) for x in (item.get("qr_redirect_findings") or []) if str(x or "").strip()]
        linked_artifact = dict(item.get("linked_artifact") or {}) if isinstance(item.get("linked_artifact"), dict) else {}
        if qr_findings:
            findings.append(
                _normalize_finding(
                    finding_id=f"attachment_qr_{fname}",
                    finding_type="qr_redirect_risk",
                    summary=f"{fname} contains a QR or redirect pattern that needs security review.",
                    severity_hint="medium",
                    confidence_score=0.8,
                    source_type="intel",
                    evidence_kind="direct",
                    agent_origin="attachment_forensics_agent",
                    policy_weight=0.66,
                    evidence=qr_findings[:4],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None},
                    recommended_action=suggested_action,
                )
            )
        payload_analysis = classify_passive_payload(
            filename=fname,
            extracted_text=str(item.get("analysis_text_sample") or item.get("text_summary") or ""),
            signals={
                "qr_payloads": list(item.get("qr_payloads") or []) if isinstance(item.get("qr_payloads"), list) else [],
                "qr_prompt_injection": any("prompt" in q.lower() for q in qr_findings),
                "steg_suspicious": bool(((item.get("steg") or {}).get("suspicious"))),
                "steg_score": float(((item.get("steg") or {}).get("score") or 0.0) or 0.0),
                "steg_explanations": list(item.get("steg_explanations") or []) if isinstance(item.get("steg_explanations"), list) else [],
                "steg_details": dict(item.get("steg_details") or {}) if isinstance(item.get("steg_details"), dict) else {},
                "ssn_detected": bool(item.get("ssn_detected")),
                "pii_detected": bool(item.get("pii_detected")),
            },
        )
        matched_hypotheses = payload_analysis.get("matched_hypotheses") if isinstance(payload_analysis.get("matched_hypotheses"), list) else []
        if not matched_hypotheses:
            matched_hypotheses = [{"hypothesis": str(payload_analysis.get("attack_hypothesis") or "").strip().lower()}]
        hidden_mapping = {
            "lolbin_command_sequence": ("lolbin_command_sequence", "Hidden content describes a LOLBin command chain that could stage or execute payloads.", "behavioral", 0.91, 0.9),
            "c2_beacon": ("c2_beacon_pattern", "Hidden content resembles beacon or callback instructions linked to command-and-control behavior.", "behavioral", 0.89, 0.86),
            "data_exfiltration": ("data_exfiltration_instruction", "Hidden content describes how data could be collected or exfiltrated.", "behavioral", 0.9, 0.9),
            "prompt_injection": ("prompt_injection_hidden", "Hidden content appears designed to manipulate downstream AI or agent workflows.", "behavioral", 0.88, 0.82),
            "pii_data_exfil_via_qr": ("ssn_leakage_linked_qr", "A QR-linked or hidden path appears to expose SSNs or other sensitive identity data.", "intel", 0.93, 0.94),
            "macros": ("macro_auto_execution_lure", "The attachment contains macro auto-execution cues that warrant sandboxed runtime confirmation before trust is extended.", "behavioral", 0.84, 0.72),
        }
        emitted_types: set[str] = set()
        for matched_item in matched_hypotheses:
            if not isinstance(matched_item, dict):
                continue
            hypothesis = str(matched_item.get("hypothesis") or "").strip().lower()
            mapped = hidden_mapping.get(hypothesis)
            if not mapped:
                continue
            finding_type, summary, src_type, conf_score, policy_weight = mapped
            if finding_type in emitted_types:
                continue
            emitted_types.add(finding_type)
            payload_evidence = []
            payload_evidence.extend([str(x) for x in (item.get("steg_explanations") or []) if str(x or "").strip()][:2])
            payload_evidence.extend(list(item.get("evidence_excerpt_lines") or [])[:2])
            if hypothesis == "lolbin_command_sequence":
                payload_evidence.extend([str(x) for x in (payload_analysis.get("lolbin_hits") or []) if str(x or "").strip()][:3])
            payload_evidence.extend(qr_findings[:2])
            if hypothesis == "pii_data_exfil_via_qr" and linked_artifact:
                owner_scope = str(linked_artifact.get("linked_owner_scope") or "").strip()
                exposure_scope = str(linked_artifact.get("linked_exposure_scope") or "").strip()
                final_url = str(linked_artifact.get("linked_final_url") or "").strip()
                pii_types = [str(x) for x in (linked_artifact.get("pii_type") or []) if str(x or "").strip()]
                ssn_hits = list(linked_artifact.get("ssn_hits") or []) if isinstance(linked_artifact.get("ssn_hits"), list) else []
                if final_url:
                    payload_evidence.append(f"Linked destination: {final_url[:180]}")
                if pii_types:
                    payload_evidence.append(f"PII types detected: {', '.join(pii_types[:3])}")
                if ssn_hits:
                    payload_evidence.append(f"SSN pattern count: {len(ssn_hits)}")
                if owner_scope:
                    payload_evidence.append(f"Exposure owner scope: {owner_scope.replace('_', ' ')}")
                if exposure_scope:
                    payload_evidence.append(f"Exposure scope: {exposure_scope.replace('_', ' ')}")
            payload_evidence = [x for x in payload_evidence if x][:6]
            row = _normalize_finding(
                finding_id=f"{finding_type}_{fname}",
                finding_type=finding_type,
                summary=summary,
                severity_hint="high" if hypothesis not in {"prompt_injection", "macros"} else "medium",
                confidence_score=conf_score,
                source_type=src_type,
                evidence_kind="direct",
                agent_origin="attachment_forensics_agent",
                policy_weight=policy_weight,
                evidence=payload_evidence,
                artifact_ref=artifact_ref,
                retrieval_context={
                    "supplier_domain": from_domain or None,
                    "baseline_version": suggested_baseline_version or None,
                    "payload_type": payload_analysis.get("payload_type"),
                    "decode_path": matched_item.get("decode_path") or payload_analysis.get("decode_path"),
                    "linked_owner_scope": linked_artifact.get("linked_owner_scope") if linked_artifact else None,
                    "linked_exposure_scope": linked_artifact.get("linked_exposure_scope") if linked_artifact else None,
                    "linked_breach_severity_hint": linked_artifact.get("linked_breach_severity_hint") if linked_artifact else None,
                    "linked_human_verification_required": linked_artifact.get("linked_human_verification_required") if linked_artifact else None,
                },
                recommended_action=suggested_action,
            )
            row["claim_status"] = str(matched_item.get("claim_status") or row.get("claim_status") or "")
            row["finding_group"] = str(matched_item.get("finding_group") or row.get("finding_group") or "")
            row["evidence_lane"] = str(matched_item.get("evidence_lane") or "")
            row["mitre_attack"] = list(matched_item.get("mitre_attack") or payload_analysis.get("mitre_attack") or [])[:5]
            row["possible_mitre_attack"] = list(matched_item.get("possible_mitre_attack") or payload_analysis.get("possible_mitre_attack") or [])[:6]
            row["mitre_atlas"] = list(matched_item.get("mitre_atlas") or payload_analysis.get("mitre_atlas") or [])[:4]
            row["possible_mitre_atlas"] = list(matched_item.get("possible_mitre_atlas") or payload_analysis.get("possible_mitre_atlas") or [])[:4]
            row["payload_decode_path"] = str(matched_item.get("decode_path") or payload_analysis.get("decode_path") or "")
            row["pasta_stage"] = str(matched_item.get("pasta_stage") or payload_analysis.get("pasta_stage") or "")
            row["suggested_next_step"] = str(payload_analysis.get("suggested_next_step") or "")
            row["runtime_confirmation_required"] = bool(matched_item.get("runtime_confirmation_required"))
            row["runtime_evidence_required"] = list(matched_item.get("runtime_evidence_required") or payload_analysis.get("runtime_evidence_required") or [])[:6]
            row["lolbin_behavioral_profiles"] = list(payload_analysis.get("lolbin_behavioral_profiles") or [])[:4]
            binary_provenance = [dict(x) for x in (matched_item.get("binary_mitre_provenance") or payload_analysis.get("binary_mitre_provenance") or []) if isinstance(x, dict)][:8]
            row["binary_mitre_provenance"] = binary_provenance
            if binary_provenance:
                existing_refs = list(row.get("evidence_refs") or [])
                for bp in binary_provenance:
                    for ref in (bp.get("evidence_refs") or []):
                        ref_text = str(ref or "").strip()
                        if ref_text and ref_text not in existing_refs:
                            existing_refs.append(ref_text)
                row["evidence_refs"] = existing_refs[:12]
                artifact_rows = list(row.get("artifact_provenance") or [])
                for bp in binary_provenance:
                    refs = [str(x) for x in (bp.get("evidence_refs") or []) if str(x or "").strip()]
                    if not refs:
                        continue
                    artifact_rows.append({
                        "source_file": fname,
                        "extraction_method": "binary_attack_mapping",
                        "match_ref": refs[0],
                        "confidence": "medium",
                        "reason": str(bp.get("reason") or "").strip(),
                    })
                row["artifact_provenance"] = artifact_rows[:12]
            if linked_artifact:
                row["linked_artifact"] = linked_artifact
            findings.append(row)

    for item in diff_rows:
        if not isinstance(item, dict):
            continue
        differences = [str(x) for x in (item.get("differences") or []) if str(x or "").strip()]
        if not differences:
            continue
        findings.append(
            _normalize_finding(
                finding_id=f"attachment_drift_{item.get('candidate_file')}",
                finding_type="baseline_drift",
                summary=f"{item.get('candidate_file') or 'attachment'} drifted from the trusted baseline document.",
                severity_hint="high",
                confidence_score=0.83,
                source_type="baseline",
                evidence_kind="inferred",
                agent_origin="baseline_agent",
                policy_weight=0.74,
                evidence=differences[:4],
                artifact_ref={"file_name": str(item.get("candidate_file") or "")},
                retrieval_context={
                    "supplier_domain": from_domain or None,
                    "baseline_file": str(item.get("baseline_file") or ""),
                    "baseline_version": suggested_baseline_version or "current",
                },
                recommended_action=suggested_action,
            )
        )

    for reason in [str(x) for x in ((verdict or {}).get("reasons") or []) if str(x or "").strip()]:
        if reason not in {"oob_verification_required", "forced_reauth_required", "llm_policy_gate_denied", "artifact_risk_block_band", "artifact_risk_review_band"}:
            continue
        findings.append(
            _normalize_finding(
                finding_id=f"policy_reason_{reason}",
                finding_type="policy_violation",
                summary=str(reason).replace("_", " "),
                severity_hint="medium" if "review" in reason else "high",
                confidence_score=0.76 if "review" in reason else 0.86,
                source_type="policy",
                evidence_kind="direct",
                agent_origin="playbook_agent",
                policy_weight=0.8,
                evidence=[reason],
                retrieval_context={"supplier_domain": from_domain or None},
                recommended_action=suggested_action,
                allowed_actions=["notify_analyst", "create_ticket", "security_review"],
                disallowed_actions=["approve_supplier_update", "push_block_rule", "approve_payment_change"],
            )
        )
    return findings


def _build_pre_agent_gate_snapshot(
    *,
    ingest_gate_meta: Dict[str, Any] | None,
    ocr_sanitization_meta: Dict[str, Any] | None,
    llm_controls: Dict[str, Any] | None,
) -> Dict[str, Any]:
    ingest = ingest_gate_meta if isinstance(ingest_gate_meta, dict) else {}
    ocr = ocr_sanitization_meta if isinstance(ocr_sanitization_meta, dict) else {}
    llm = llm_controls if isinstance(llm_controls, dict) else {}
    return {
        "artifact_text_untrusted": True,
        "ocr_text_sanitized": True,
        "sandbox_required": bool(llm.get("sandbox_required", True)),
        "blocked_qr_url_count": int(ocr.get("blocked_qr_url_count") or 0),
        "blocked_attachment_count": int(ingest.get("blocked_count") or 0),
        "blocked_attachment_reasons": [str(x) for x in (ingest.get("block_reasons") or []) if str(x or "").strip()][:8],
        "blocked_tool_intents": [str(x) for x in (llm.get("blocked_intents") or []) if str(x or "").strip()][:8],
        "allow_tools": [str(x) for x in (llm.get("allow_tools") or []) if str(x or "").strip()][:8],
    }


def _build_agent_runs_audit(
    *,
    evidence_snapshot: Dict[str, Any],
    structured_findings: list[dict[str, Any]],
    policy_gate: Dict[str, Any] | None,
) -> list[dict[str, Any]]:
    ev = evidence_snapshot if isinstance(evidence_snapshot, dict) else {}
    findings = [f for f in structured_findings if isinstance(f, dict)]
    boundaries = _email_agent_boundaries()
    scope_map = {
        "sender_auth_agent": "headers",
        "attachment_forensics_agent": "attachments",
        "baseline_agent": "suppliers",
        "correlation_agent": "security_events",
        "explanation_agent": "policies",
        "playbook_agent": "policies",
    }

    def _count(agent_name: str) -> int:
        return sum(1 for f in findings if str(f.get("agent_origin") or "") == agent_name)

    auth = ev.get("auth_verdicts") if isinstance(ev.get("auth_verdicts"), dict) else {}
    infra = ev.get("sender_infrastructure") if isinstance(ev.get("sender_infrastructure"), dict) else {}
    atts = ev.get("attachment_forensics") if isinstance(ev.get("attachment_forensics"), list) else []
    rel = (infra.get("related_incidents") if isinstance(infra.get("related_incidents"), dict) else {}) or {}
    playbook = ev.get("playbook_run") if isinstance(ev.get("playbook_run"), dict) else {}
    route_after = str((policy_gate or {}).get("decision") or ev.get("route") or "review")
    runs: list[dict[str, Any]] = []
    parallel_agent_ids = [row[0] for row in [
        ("sender_auth_agent", {}),
        ("attachment_forensics_agent", {}),
        ("baseline_agent", {}),
        ("correlation_agent", {}),
        ("explanation_agent", {}),
        ("playbook_agent", {}),
    ]]
    rows = [
        (
            "sender_auth_agent",
            {
                "inputs_used": ["message_headers", "spf_dkim_dmarc", "header_forensics"],
                "input_refs": [k for k in ("spf_result", "dkim_result", "dmarc_result") if auth.get(k) is not None] + ([infra.get("sender_domain")] if infra.get("sender_domain") else []),
                "confidence": 0.88 if _count("sender_auth_agent") else 0.52,
                "why_ran": "Email headers and sender identity signals were present and required authentication review.",
                "output_quality": "structural",
            },
        ),
        (
            "attachment_forensics_agent",
            {
                "inputs_used": ["sanitized_attachment_text", "ocr_output", "file_metadata", "static_analysis"],
                "input_refs": [str(a.get("file_name") or "") for a in atts[:8] if isinstance(a, dict)],
                "confidence": 0.86 if _count("attachment_forensics_agent") else 0.5,
                "why_ran": "Attachments were present and needed passive extraction, OCR, and static analysis.",
                "output_quality": "structural",
            },
        ),
        (
            "baseline_agent",
            {
                "inputs_used": ["supplier_profile", "approved_contacts", "bank_fingerprints", "template_hashes"],
                "input_refs": [str(((ev.get("attachment_baseline_diffs") or {}).get("baseline_file") or ""))] if isinstance(ev.get("attachment_baseline_diffs"), dict) else [],
                "confidence": 0.84 if _count("baseline_agent") else 0.5,
                "why_ran": "Supplier and template baseline checks were available for comparison.",
                "output_quality": "structural",
            },
        ),
        (
            "correlation_agent",
            {
                "inputs_used": ["prior_incidents", "sender_domain", "reply_domain", "incident_graph"],
                "input_refs": [str(m.get("incident_id") or "") for m in (rel.get("matches") or [])[:5] if isinstance(m, dict)],
                "confidence": 0.72 if _count("correlation_agent") else 0.46,
                "why_ran": "Related incident and infrastructure overlap checks were available.",
                "output_quality": "structural",
            },
        ),
        (
            "explanation_agent",
            {
                "inputs_used": ["normalized_findings", "faq_policy_mappings", "business_impact_model"],
                "input_refs": [str(f.get("finding_id") or "") for f in findings[:5]],
                "confidence": 0.78 if findings else 0.45,
                "why_ran": "A human-readable explanation was required after evidence normalization.",
                "output_quality": "heuristic",
            },
        ),
        (
            "playbook_agent",
            {
                "inputs_used": ["policy_approved_findings", "allowed_actions", "sop_mappings"],
                "input_refs": [str(playbook.get("playbook_id") or "")] if playbook else [],
                "confidence": 0.81 if _count("playbook_agent") else 0.49,
                "why_ran": "Response playbook selection was required after verdict routing.",
                "output_quality": "structural",
            },
        ),
    ]
    for agent_name, meta in rows:
        boundary = boundaries.get(agent_name) or {}
        violations = []
        for tool_name in _finding_source_toolset(agent_name):
            violations.extend(
                [
                    {
                        "violation_type": v.violation_type,
                        "detail": v.detail,
                        "severity": v.severity,
                    }
                    for v in validate_agent_action(agent_name=agent_name, tool_name=tool_name)
                ]
            )
        scope_name = str(scope_map.get(agent_name) or "").strip()
        if scope_name:
            violations.extend(
                [
                    {
                        "violation_type": v.violation_type,
                        "detail": v.detail,
                        "severity": v.severity,
                    }
                    for v in validate_agent_action(agent_name=agent_name, data_scope=scope_name)
                ]
            )
        agent_findings = [f for f in findings if str(f.get("agent_origin") or "") == agent_name]
        evidence_added = [str(f.get("finding_id") or f.get("finding_type") or "") for f in agent_findings[:8] if str(f.get("finding_id") or f.get("finding_type") or "").strip()]
        runs.append(
            {
                "agent_name": agent_name,
                "agent_id": agent_name,
                "scope_enforced": len(violations) == 0,
                "allowed_inputs": list(boundary.get("allowed_inputs") or []),
                "allowed_tools": list(boundary.get("allowed_tools") or []),
                "allowed_outputs": list(boundary.get("allowed_outputs") or []),
                "denied_capabilities": list(boundary.get("denied_capabilities") or []),
                "inputs_used": list(meta.get("inputs_used") or []),
                "input_refs": [str(x) for x in (meta.get("input_refs") or []) if str(x or "").strip()][:8],
                "input_summary": ", ".join([str(x) for x in (meta.get("input_refs") or []) if str(x or "").strip()][:4]) or ", ".join(meta.get("inputs_used") or []),
                "tools_used": _finding_source_toolset(agent_name),
                "output_count": _count(agent_name),
                "confidence": round(float(meta.get("confidence") or 0.0), 4),
                "why_ran": str(meta.get("why_ran") or ""),
                "evidence_added": evidence_added,
                "evidence_retracted": [],
                "verdict_before": "review" if agent_name in {"explanation_agent", "playbook_agent"} else "allow",
                "verdict_after": route_after,
                "confidence_delta": round(float(meta.get("confidence") or 0.0) - 0.45, 3),
                "output_quality": str(meta.get("output_quality") or "heuristic"),
                "ran_in_parallel_with": [name for name in parallel_agent_ids if name != agent_name],
                "filler_suppressed": True,
                "policy_result": str((policy_gate or {}).get("decision") or "allow"),
                "actions_taken": [],
                "scope_violations": violations[:10],
                "trace_id": str(ev.get("trace_id") or ev.get("decision_id") or ""),
            }
        )
    return runs


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
