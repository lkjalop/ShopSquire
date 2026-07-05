"""DMARC aggregate-report parsing + BEC heuristics (extracted from email_security.py).

Self-contained: parse a DMARC aggregate report (raw XML or a .zip of one), summarize SPF/DKIM
pass counts + top failing sources, and — for a high fail rate — emit telemetry and auto-ticket.
Plus a minimal keyword/homograph BEC indicator helper. Pure parsing + best-effort side effects;
never raises into a caller. Vertical-blind.
"""
from __future__ import annotations

import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, Tuple

from src.app.config import get_settings, load_feature_flags
from src.app.observability.telemetry import telemetry_emit
from src.app.services.ticketing import TicketingAgent


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
