from __future__ import annotations

from typing import Any, Dict, Tuple
import xml.etree.ElementTree as ET
import zipfile
import io
import re

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
from src.app.security.siem_adapter import build_normalized_security_event, emit_security_handoff
from src.app.security.threat_enrichment import enrich_context, infer_kill_chain_stage
import time

_RATE_BUCKETS: dict[str, list[float]] = {}


def _hash16(value: str | None) -> str | None:
    if not value:
        return None
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
                insert_cols = [c for c in payload.keys() if c in cols]
                if not insert_cols:
                    return
                stmt = text(
                    "INSERT INTO email_security_incidents (" + ", ".join(insert_cols) + ") VALUES (" +
                    ", ".join([":" + c for c in insert_cols]) + ")"
                )
                db.execute(stmt, {k: payload[k] for k in insert_cols})
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

    # Accept raw base64 attachment bytes in the evaluate path and hydrate deterministic metadata/text.
    try:
        email = hydrate_attachments_from_bytes(email)
    except Exception:
        email = dict(email)

    extracted = extract_indicators(email, tenant_id=tenant_id)
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
        extracted["indicators"] = indicators
        extracted.setdefault("meta", {})["sender_trust"] = trust
    except Exception:
        trust = {}

    # DMARC fail is considered if caller passed a boolean in email["dmarc_fail"]. Default False.
    dmarc_fail = bool(email.get("dmarc_fail", False))
    spf_result = str(email.get("spf_result") or "").lower()
    dkim_result = str(email.get("dkim_result") or "").lower()
    dmarc_result = str(email.get("dmarc_result") or "").lower()
    dmarc_policy = str(email.get("dmarc_policy") or "").lower()
    v = compute_verdict(email, extracted, dmarc_fail=dmarc_fail)
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
    # Enforce auth-verdict gate: when sender policy is quarantine/reject and alignment fails, force security review.
    if (dmarc_result in ("fail", "reject", "quarantine") or dmarc_fail) and dmarc_policy in ("reject", "p=reject", "quarantine", "p=quarantine"):
        v["severity"] = "error"
        v["route"] = "security_review"
        v["verdict_action"] = "security_review"
        v["escalation"] = "security_middleware"
        v["reasons"] = list(dict.fromkeys((v.get("reasons") or []) + ["auth_alignment_failed_under_dmarc_policy"]))
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
        try:
            v["evidence_snapshot"]["artifact_intel"] = {
                "parsed_fields": (artifact_intel.get("parsed_fields") if isinstance(artifact_intel, dict) else {}) or {},
                "baseline_checks": (artifact_intel.get("baseline_checks") if isinstance(artifact_intel, dict) else {}) or {},
                "forensics_details": (artifact_intel.get("forensics_details") if isinstance(artifact_intel, dict) else {}) or {},
                "signal_scores": (artifact_intel.get("signal_scores") if isinstance(artifact_intel, dict) else {}) or {},
            }
        except Exception:
            pass
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
    # P1 enrichment and safe detonation (best-effort, non-blocking).
    enrichment_t0 = time.perf_counter()
    enrichment_error = None
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
    except Exception:
        pass
    detonation_t0 = time.perf_counter()
    detonation_error = None
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
    except Exception:
        pass
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
    except Exception:
        pass

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
        "llm_assist": llm_assist,
        "sender_trust": trust,
        "threat_correlation": threat,
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
                    except Exception:
                        pass
                except Exception:
                    pass
        else:
            # Emit aggregation telemetry but do not open ticket
            ticket_rate_limited = True
            try:
                telemetry_emit({"type": "email_security", "subtype": "ticket_rate_limited", "count": count, "tenant_id": tenant_id}, severity=v["severity"], sourcetype="shopsquire:security")
            except Exception:
                pass
            try:
                from src.app.observability.metrics import record_email_security_rate_limited

                record_email_security_rate_limited(tenant_id)
            except Exception:
                pass

    # Bitemporal decision + trace events
    decision_id = None
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
            },
            proposed_action={
                "severity": v.get("severity"),
                "verdict_action": v.get("verdict_action"),
                "route": v.get("route"),
                "escalation": v.get("escalation"),
                "policy_gate": v.get("policy_gate"),
                "risk_band": v.get("risk_band"),
                "reasons": v.get("reasons"),
            },
            agent_reasoning="rule_first_email_security",
            policy_version="email_security_v1",
            approval_required=bool(v.get("route") in ("human_review", "security_review")),
            execution_status="review_required" if v.get("route") in ("human_review", "security_review") else "approved",
            event_type="email_security_verdict",
        )
    except Exception:
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
                    "ioc_counts": (v.get("evidence_snapshot") or {}).get("ioc_counts"),
                    "tags": v.get("tags"),
                    "detonation": v.get("detonation"),
                    "enrichment": v.get("enrichment"),
                    "sender_trust": trust,
                    "artifact_intel": (v.get("evidence_snapshot") or {}).get("artifact_intel"),
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
    except Exception:
        pass

    v["decision_id"] = decision_id
    v["decision_trace_id"] = decision_id

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
