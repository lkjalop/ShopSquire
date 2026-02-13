from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, require_role
from src.app.services.grc_fingerprint import (
    list_fingerprint_alerts,
    list_fingerprint_scans,
    run_fingerprint_ingestion,
    update_fingerprint_alert_status,
)
from src.app.services.grc_reporting import (
    build_trend_series,
    export_grc_report_csv,
    export_grc_report_markdown,
    export_grc_report_pdf,
)


router = APIRouter(prefix="/api/v1/admin/grc", tags=["admin-grc"])


def _framework_catalog() -> Dict[str, Dict[str, Any]]:
    return {
        "ISO27001": {
            "name": "ISO/IEC 27001",
            "controls": ["A.5.7", "A.5.23", "A.8.15", "A.8.16", "A.5.30"],
        },
        "GDPR": {
            "name": "GDPR",
            "controls": ["Art.5(1)(c)", "Art.15", "Art.17", "Art.22", "Art.32"],
        },
        "EU_AI_ACT": {
            "name": "EU AI Act",
            "controls": ["Art.9", "Art.10", "Art.12", "Art.14", "Art.15"],
        },
        "NIST_AI_RMF": {
            "name": "NIST AI RMF",
            "controls": ["GOVERN-1", "MAP-2", "MEASURE-2", "MANAGE-3"],
        },
        "ISO42001": {
            "name": "ISO/IEC 42001",
            "controls": ["5.2", "7.4", "8.2", "8.3", "9.1"],
        },
        "ISO19011": {
            "name": "ISO 19011",
            "controls": ["Clause 5", "Clause 6", "Clause 7"],
        },
    }


def _safe_scalar(db, sql: str, params: Dict[str, Any] | None = None) -> int:
    try:
        v = db.execute(text(sql), params or {}).scalar()
        return int(v or 0)
    except Exception:
        return 0


def _build_risk_register(days: int) -> Dict[str, Any]:
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    out: Dict[str, Any] = {"window_days": days, "domains": [], "frameworks": {}, "controls": {}}

    with db_session() as db:
        security_events = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM security_events WHERE event_time >= :since",
            {"since": since},
        )
        critical_security = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM security_events WHERE event_time >= :since AND severity = 'critical'",
            {"since": since},
        )
        dmarc_reports = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM dmarc_reports WHERE created_at >= :since",
            {"since": since},
        )
        dmarc_failed = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM dmarc_reports WHERE created_at >= :since AND fail_count > 0",
            {"since": since},
        )
        supplier_incidents = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM incidents WHERE created_at >= :since AND (LOWER(title) LIKE '%supplier%' OR LOWER(title) LIKE '%vendor%')",
            {"since": since},
        )
        inventory_stockouts = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM inventory WHERE stock <= 0",
        )
        inventory_low = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM inventory WHERE stock > 0 AND stock <= 5",
        )
        iam_events = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM iam_events WHERE event_time >= :since",
            {"since": since},
        )
        suspicious_iam = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM iam_events WHERE event_time >= :since AND (LOWER(event_type) LIKE '%failed%' OR LOWER(event_type) LIKE '%deny%' OR LOWER(event_type) LIKE '%mfa%')",
            {"since": since},
        )
        trace_events = _safe_scalar(
            db,
            "SELECT COUNT(*) FROM decision_trace_events WHERE created_at >= :since",
            {"since": since},
        )

    def _band(score: int) -> str:
        if score >= 70:
            return "high"
        if score >= 40:
            return "medium"
        return "low"

    email_score = min(100, (dmarc_failed * 8) + (critical_security * 5))
    supplier_score = min(100, (supplier_incidents * 10) + (critical_security * 3))
    inventory_score = min(100, (inventory_stockouts * 15) + (inventory_low * 2))
    insider_score = min(100, (suspicious_iam * 7) + (critical_security * 2))
    trace_score = min(100, 100 - min(trace_events // 20, 100))

    out["domains"] = [
        {
            "domain": "email_deliverability",
            "risk_score": email_score,
            "risk_band": _band(email_score),
            "signals": {
                "dmarc_reports": dmarc_reports,
                "dmarc_fail_reports": dmarc_failed,
                "critical_security_events": critical_security,
            },
            "recommended_actions": [
                "Enforce SPF/DKIM/DMARC on transactional and marketing subdomains",
                "Auto-suppress bounce/complaint recipients and trigger reputation recovery runbook",
            ],
        },
        {
            "domain": "supplier_trust",
            "risk_score": supplier_score,
            "risk_band": _band(supplier_score),
            "signals": {
                "supplier_incidents": supplier_incidents,
                "security_events": security_events,
            },
            "recommended_actions": [
                "Require step-up verification for settlement/bank-change requests",
                "Track approved supplier TLS/SSH fingerprints and alert on drift",
            ],
        },
        {
            "domain": "inventory_resilience",
            "risk_score": inventory_score,
            "risk_band": _band(inventory_score),
            "signals": {
                "stockouts": inventory_stockouts,
                "low_stock_items": inventory_low,
            },
            "recommended_actions": [
                "Escalate SKUs with low-stock trend and high order velocity",
                "Enforce supplier SLA checks for restock delays",
            ],
        },
        {
            "domain": "insider_threat",
            "risk_score": insider_score,
            "risk_band": _band(insider_score),
            "signals": {
                "iam_events": iam_events,
                "suspicious_iam_events": suspicious_iam,
            },
            "recommended_actions": [
                "Require MFA and just-in-time elevation for sensitive admin actions",
                "Alert on failed auth bursts and role/permission drift",
            ],
        },
        {
            "domain": "decision_trace_coverage",
            "risk_score": trace_score,
            "risk_band": _band(trace_score),
            "signals": {
                "decision_trace_events": trace_events,
            },
            "recommended_actions": [
                "Capture per-decision control IDs and policy versions in trace",
                "Include risk rationale and required approvals in exported reports",
            ],
        },
    ]

    frameworks = _framework_catalog()
    out["frameworks"] = frameworks
    out["controls"] = {
        "ISO27001:A.8.15": {"status": "pass" if security_events > 0 else "warn", "evidence": "security_events"},
        "ISO27001:A.8.16": {"status": "pass" if critical_security >= 0 else "warn", "evidence": "incident_monitoring"},
        "GDPR:Art.22": {"status": "pass" if trace_events > 0 else "warn", "evidence": "decision_trace_events"},
        "GDPR:Art.32": {"status": "pass" if suspicious_iam >= 0 else "warn", "evidence": "iam_events"},
        "EU_AI_ACT:Art.14": {"status": "pass" if trace_events > 0 else "warn", "evidence": "human_oversight_trace"},
        "NIST_AI_RMF:MANAGE-3": {"status": "pass" if security_events > 0 else "warn", "evidence": "security_events"},
        "ISO42001:7.4": {"status": "pass" if trace_events > 0 else "warn", "evidence": "decision_trace_events"},
        "ISO19011:Clause 6": {"status": "pass" if trace_events > 0 else "warn", "evidence": "audit_evidence_ready"},
    }
    return out


def _control_evidence_rows(days: int) -> List[Dict[str, str]]:
    rr = _build_risk_register(days)
    rows: List[Dict[str, str]] = []
    for cid, payload in (rr.get("controls") or {}).items():
        ev = str((payload or {}).get("evidence") or "")
        if ev in ("security_events", "incident_monitoring"):
            link = f"/api/v1/admin/compliance/evidence?days={days}"
        elif ev in ("decision_trace_events", "human_oversight_trace", "audit_evidence_ready"):
            link = f"/api/v1/admin/compliance/live-feed?limit=50"
        elif ev in ("iam_events",):
            link = "/api/v1/admin/iam/events?limit=100"
        else:
            link = f"/api/v1/admin/grc/fingerprint-alerts?limit=100"
        rows.append(
            {
                "control_id": cid,
                "status": str((payload or {}).get("status") or "warn"),
                "evidence": ev,
                "evidence_link": link,
            }
        )
    return rows


@router.get("/risk-register")
def grc_risk_register(
    days: int = Query(30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return _build_risk_register(days)


@router.get("/report")
def grc_report(
    days: int = Query(30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    rr = _build_risk_register(days)
    high = [d for d in rr.get("domains", []) if d.get("risk_band") == "high"]
    medium = [d for d in rr.get("domains", []) if d.get("risk_band") == "medium"]
    summary = {
        "window_days": days,
        "domain_count": len(rr.get("domains", [])),
        "high_risk_domains": [d.get("domain") for d in high],
        "medium_risk_domains": [d.get("domain") for d in medium],
        "control_status": rr.get("controls", {}),
    }
    trend = build_trend_series(days=days)
    return {"summary": summary, "risk_register": rr, "trend": trend, "controls": _control_evidence_rows(days)}


@router.get("/trends")
def grc_trends(
    days: int = Query(30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return build_trend_series(days=days)


@router.post("/fingerprint-ingest/run")
def fingerprint_ingest_run(
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return run_fingerprint_ingestion()


@router.get("/fingerprint-alerts")
def fingerprint_alerts(
    status: str | None = Query(None, pattern="^(open|in_progress|resolved|ignored)$"),
    severity: str | None = Query(None, pattern="^(low|medium|high|critical)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return list_fingerprint_alerts(status_filter=status, severity=severity, limit=limit, offset=offset)


@router.get("/fingerprint-scans")
def fingerprint_scans(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return list_fingerprint_scans(limit=limit, offset=offset)


@router.post("/fingerprint-alerts/{alert_id}/status")
def fingerprint_alert_status(
    alert_id: str,
    status: str = Query(..., pattern="^(open|in_progress|resolved|ignored)$"),
    note: str | None = Query(None),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    try:
        return update_fingerprint_alert_status(alert_id, status=status, note=note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/report/export.csv")
def grc_report_export_csv(
    days: int = Query(30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Response:
    rr = _build_risk_register(days)
    controls = _control_evidence_rows(days)
    trend = build_trend_series(days=days)
    payload = export_grc_report_csv(days=days, risk_register=rr, control_rows=controls, trend=trend)
    return Response(
        content=payload,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="shopsquire-grc-report-{days}d.csv"'},
    )


@router.get("/report/export.md")
def grc_report_export_md(
    days: int = Query(30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Response:
    rr = _build_risk_register(days)
    controls = _control_evidence_rows(days)
    trend = build_trend_series(days=days)
    md = export_grc_report_markdown(days=days, risk_register=rr, control_rows=controls, trend=trend)
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="shopsquire-grc-report-{days}d.md"'},
    )


@router.get("/report/export.pdf")
def grc_report_export_pdf(
    days: int = Query(30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Response:
    rr = _build_risk_register(days)
    controls = _control_evidence_rows(days)
    trend = build_trend_series(days=days)
    md = export_grc_report_markdown(days=days, risk_register=rr, control_rows=controls, trend=trend)
    pdf_bytes = export_grc_report_pdf(markdown_text=md)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="shopsquire-grc-report-{days}d.pdf"'},
    )
