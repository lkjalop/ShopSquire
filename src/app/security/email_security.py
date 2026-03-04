from __future__ import annotations

from typing import Any, Dict, Tuple
import xml.etree.ElementTree as ET
import zipfile
import io
import re
import os
import logging

from src.app.observability.telemetry import telemetry_emit
from src.app.config import load_feature_flags, get_settings
from src.app.services.ticketing import TicketingAgent
import hashlib
from src.app.services.decision_log import log_decision, log_trace_event

from src.app.security.email_security_rules import extract_indicators
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
from src.app.security.bec_kill_chain import infer_bec_kill_chain
from src.app.security.bimi_verifier import verify_bimi_provider_backed
from src.app.security.siem_adapter import build_normalized_security_event, emit_security_handoff
from src.app.security.threat_enrichment import enrich_context, infer_kill_chain_stage
import time
from src.app.services.intake_gate import (
    normalize_email_intake,
    sanitize_attachment_ocr_for_llm,
    strict_attachment_ingest_gate,
)
from src.app.services.playbook_engine import start_playbook_run, append_playbook_step, execute_typed_actions, complete_playbook_run
from src.app.security.framework_correlation import correlate_security_analysis
from src.app.services.trust_routing import fuse_security_trust_score

_RATE_BUCKETS: dict[str, list[float]] = {}
logger = logging.getLogger("shopsquire.email_security")


def _hash16(value: str | None) -> str | None:
    if not value:
        return None


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
    summary = (
        f"Rule-first verdict={verdict.get('verdict_action')} route={verdict.get('route')}. "
        f"Signals={', '.join(ind_types[:8]) or 'none'}. Subject='{subject[:120]}'."
    )
    secondary_risk = min(1.0, (len(ind_types) * 0.08) + (0.25 if verdict.get("severity") == "error" else 0.0))
    return {
        "enabled": enabled,
        "source": "heuristic_assist",
        "summary": summary,
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
) -> None:
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
                    return
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
                    return
                db.commit()
        except Exception:
            # Best-effort persistence (schema may be absent in SQLite-only envs).
            return


def _parse_dmarc_xml(xml_bytes: bytes) -> Dict[str, Any]:
    """Parse a DMARC aggregate report XML payload into a minimal summary.

    Returns counts of total records, pass/fail for SPF/DKIM, and top failing sources.
    """
    summary: Dict[str, Any] = {
        "total": 0,
        "spf_pass": 0,
        "dkim_pass": 0,
        "fail_sources": {},
        "org": None,
        "domain": None,
    }
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return summary
    try:
        # Common DMARC aggregate format has <feedback> root; tolerate variants
        domain = None
        org = None
        try:
            domain = (root.findtext("report_metadata/domain") or root.findtext("policy_published/domain") or None)
            org = root.findtext("report_metadata/org_name") or None
        except Exception:
            pass
        summary["domain"] = domain
        summary["org"] = org
        for rec in root.findall("record"):
            summary["total"] += 1
            try:
                # policy_evaluated fields: dkim, spf are usually 'pass'/'fail'
                pe = rec.find("row/policy_evaluated")
                dkim = pe.findtext("dkim") if pe is not None else None
                spf = pe.findtext("spf") if pe is not None else None
                if (dkim or "").lower() == "pass":
                    summary["dkim_pass"] += 1
                if (spf or "").lower() == "pass":
                    summary["spf_pass"] += 1
            except Exception:
                pass
            try:
                src_ip = rec.findtext("row/source_ip") or "unknown"
                if src_ip:
                    d = summary["fail_sources"].get(src_ip, 0)
                    # Consider a fail if either SPF or DKIM did not pass
                    if (dkim or "").lower() != "pass" or (spf or "").lower() != "pass":
                        summary["fail_sources"][src_ip] = d + 1
            except Exception:
                pass
    except Exception:
        pass
    return summary


def parse_dmarc_aggregate(data: bytes) -> Dict[str, Any]:
    """Parse DMARC aggregate report data.

    Supports raw XML or .zip containing a single XML file.
    """
    try:
        # Detect ZIP by signature
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".xml"):
                        with zf.open(name) as f:
                            return _parse_dmarc_xml(f.read())
            # fallback: take first file
            with zf.open(zf.namelist()[0]) as f:  # type: ignore
                return _parse_dmarc_xml(f.read())
        return _parse_dmarc_xml(data)
    except Exception:
        return {"total": 0, "spf_pass": 0, "dkim_pass": 0, "fail_sources": {}, "org": None, "domain": None}


def detect_bec_indicators(subject: str, body: str) -> Tuple[bool, Dict[str, Any]]:
    """Minimal BEC indicator detector using simple heuristics.

    Flags risky language and reply-to mismatches.
    """
    indicators = {
        "keywords": [],
        "reply_to_mismatch": False,
        "domain_lookalike": False,
    }
    risky_words = [
        r"urgent",
        r"wire\s+transfer",
        r"gift\s*cards",
        r"asap",
        r"confidential",
        r"bank\s+details",
    ]
    try:
        text = f"{subject}\n{body}".lower()
        for kw in risky_words:
            if re.search(kw, text):
                indicators["keywords"].append(kw)
    except Exception:
        pass
    # domain lookalike heuristic: common homograph patterns
    try:
        if re.search(r"@.*(?:micros0ft|amaz0n|paypa1)\.com", text):
            indicators["domain_lookalike"] = True
    except Exception:
        pass
    # reply-to mismatch (placeholder: caller should detect and pass a flag)
    return (bool(indicators["keywords"] or indicators["domain_lookalike"] or indicators["reply_to_mismatch"]), indicators)


def process_dmarc_report(data: bytes, tenant_id: str | None = None) -> Dict[str, Any]:
    """Process a DMARC aggregate report, emit telemetry, and auto-ticket if severity high.

    Returns the computed summary.
    """
    summary = parse_dmarc_aggregate(data)
    total = int(summary.get("total") or 0)
    spf_pass = int(summary.get("spf_pass") or 0)
    dkim_pass = int(summary.get("dkim_pass") or 0)
    fail = max(total - max(spf_pass, dkim_pass), 0)
    fail_rate = (fail / total) if total > 0 else 0.0
    thresholds = {}
    try:
        flags_path = os.getenv("FEATURE_FLAGS_PATH") or get_settings().feature_flags_path
        thresholds = (load_feature_flags(flags_path) or {}).get("SECURITY_THRESHOLDS", {})
    except Exception:
        thresholds = {}
    warn_thr = float(thresholds.get("DMARC_FAIL_WARN", 0.25))
    err_thr = float(thresholds.get("DMARC_FAIL_ERROR", 0.5))
    severity = "info"
    risk = "low"
    if fail_rate >= warn_thr:
        severity = "warning"
        risk = "medium"
    if fail_rate >= err_thr:
        severity = "error"
        risk = "high"
    evt = {
        "type": "email_security",
        "subtype": "dmarc_aggregate",
        "tenant_id": tenant_id,
        "domain": summary.get("domain"),
        "org": summary.get("org"),
        "total": total,
        "spf_pass": spf_pass,
        "dkim_pass": dkim_pass,
        "fail_rate": round(fail_rate, 4),
        "top_fail_sources": dict(sorted((summary.get("fail_sources") or {}).items(), key=lambda kv: kv[1], reverse=True)[:5]),
        "risk": risk,
        "tags": ["email_security", "dmarc"],
    }
    try:
        telemetry_emit(evt, severity=severity, sourcetype="shopsquire:security")
    except Exception:
        pass
    if risk == "high":
        try:
            TicketingAgent().create_ticket(
                title=f"DMARC high fail rate for {summary.get('domain')}",
                description=f"Fail rate {fail_rate:.2%}; top failing sources: {list(evt['top_fail_sources'].items())}",
                severity="high",
                tenant_id=tenant_id or "default",
                reason_code="dmarc_fail_rate_high",
                cv_summary=evt,
                approval_required=False,
            )
        except Exception:
            pass
    return summary


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

    # Strict ingest controls before deep parsing: MIME/ext/size/archive/AV.
    try:
        email, ingest_gate_meta = strict_attachment_ingest_gate(email)
    except Exception:
        ingest_gate_meta = {"gate": "strict_attachment_ingest", "blocked": False, "error": "ingest_gate_failed"}

    # Accept raw base64 attachment bytes in the evaluate path and hydrate deterministic metadata/text.
    try:
        email = hydrate_attachments_from_bytes(email)
    except Exception:
        email = dict(email)

    # OCR text sanitization + QR URL allowlist enforcement before any model-assisted processing.
    try:
        email, ocr_sanitization_meta = sanitize_attachment_ocr_for_llm(email)
    except Exception:
        ocr_sanitization_meta = {"gate": "ocr_qr_sanitization", "blocked_qr_url_count": 0, "error": "ocr_sanitize_failed"}

    extracted = extract_indicators(email, tenant_id=tenant_id)
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
        critical = {"dangerous_tool_intent", "prompt_injection", "lolbin_command", "c2_beacon_pattern", "data_exfil_intent"}
        if auth_all_pass and ((from_domain.lower() in trusted_domains) or (external_sender is False)):
            if not (ind_types_set & critical) and v.get("route") in ("human_review", None):
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
        v["evidence_snapshot"]["mailbox_compromise"] = mailbox_compromise or {}
        try:
            v["evidence_snapshot"]["artifact_intel"] = {
                "parsed_fields": (artifact_intel.get("parsed_fields") if isinstance(artifact_intel, dict) else {}) or {},
                "baseline_checks": (artifact_intel.get("baseline_checks") if isinstance(artifact_intel, dict) else {}) or {},
                "forensics_details": (artifact_intel.get("forensics_details") if isinstance(artifact_intel, dict) else {}) or {},
                "signal_scores": (artifact_intel.get("signal_scores") if isinstance(artifact_intel, dict) else {}) or {},
            }
        except Exception:
            pass
        v["evidence_snapshot"]["intake_gate"] = intake_meta
        v["evidence_snapshot"]["attachment_ingest_gate"] = ingest_gate_meta
        v["evidence_snapshot"]["ocr_qr_sanitization"] = ocr_sanitization_meta
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
    except Exception:
        pass
    try:
        if isinstance(v.get("evidence_snapshot"), dict):
            v["evidence_snapshot"]["intake_gate"] = intake_meta
            v["evidence_snapshot"]["attachment_ingest_gate"] = ingest_gate_meta
            v["evidence_snapshot"]["ocr_qr_sanitization"] = ocr_sanitization_meta
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
        "bec_kill_chain": bec_kill_chain,
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
            sig = {
                "dmarc_fail": bool(dmarc_fail),
                "prompt_injection": any(str((i or {}).get("type") or "") == "prompt_injection" for i in (v.get("indicators") or [])),
                "dangerous_tool_intent": any(str((i or {}).get("type") or "") == "dangerous_tool_intent" for i in (v.get("indicators") or [])),
                "data_exfiltration": any(str((i or {}).get("type") or "") in ("data_exfil_intent",) for i in (v.get("indicators") or [])),
                "email_c2_beaconing": any(str((i or {}).get("type") or "") == "c2_beacon_pattern" for i in (v.get("indicators") or [])),
                "unicode_confusable": any(str((i or {}).get("type") or "") in ("confusable_homoglyph_domain", "vendor_homoglyph_impersonation") for i in (v.get("indicators") or [])),
                "thread_hijack": bool(email.get("prior_reply_chain_id")) and bool(email.get("reply_chain_id")) and str(email.get("prior_reply_chain_id")) != str(email.get("reply_chain_id")),
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
                "ioc_counts": (v.get("evidence_snapshot") or {}).get("ioc_counts"),
                "artifact_intel": (v.get("evidence_snapshot") or {}).get("artifact_intel"),
                "intake_gate": (v.get("evidence_snapshot") or {}).get("intake_gate"),
                "attachment_ingest_gate": (v.get("evidence_snapshot") or {}).get("attachment_ingest_gate"),
                "ocr_qr_sanitization": (v.get("evidence_snapshot") or {}).get("ocr_qr_sanitization"),
                "trust_case": trust_case,
            },
        )
    except Exception as exc:
        _record_runtime_error(runtime_errors, stage="security_framework_correlation", exc=(exc if isinstance(exc, Exception) else RuntimeError(str(exc))))
        security_analysis = None

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
                },
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
                action_exec = execute_typed_actions(run_id=run_id, actions=actions, context={"channel": "email", "decision_id": decision_id})
                append_playbook_step(run_id=run_id, event_type="actions", status="completed", evidence={"result": action_exec})
                complete_playbook_run(run_id=run_id, status="completed", outcome="executed")
                v["playbook_run"] = {"run_id": run_id, "actions": action_exec}
    except Exception:
        pass

    # Persist incident (redacted) for admin drilldown/grouping
    try:
        meta = extracted.get("meta") if isinstance(extracted, dict) else {}
        supplier_key = (meta or {}).get("from_domain") or (meta or {}).get("reply_to_domain")
    except Exception:
        supplier_key = None
    _persist_incident(
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

    return v
