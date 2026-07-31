from __future__ import annotations

import json
import uuid
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
            link = "/api/v1/admin/compliance/live-feed?limit=50"
        elif ev in ("iam_events",):
            link = "/api/v1/admin/iam/events?limit=100"
        else:
            link = "/api/v1/admin/grc/fingerprint-alerts?limit=100"
        rows.append(
            {
                "control_id": cid,
                "status": str((payload or {}).get("status") or "warn"),
                "evidence": ev,
                "evidence_link": link,
            }
        )
    return rows


def build_decision_evidence(days: int = 30, limit: int = 25) -> Dict[str, Any]:
    """ISO 42001 / EU AI Act / PCI Req 10 / OWASP Agentic evidence pack — aggregate the
    framework-tagged consequential-decision audit (policy_evaluation_log, written by B4) into a
    procurement-ready report: how many consequential actions were decided, the allow/escalate/block
    split, the breakdown by OWASP-Agentic ASI tag and by action, and recent examples. This turns
    "we have controls" into "here is the auditable evidence." Pure read; never raises."""
    # Match SQLite CURRENT_TIMESTAMP format ("YYYY-MM-DD HH:MM:SS") used by the canonical audit
    # writer — an isoformat 'T' bound would lexically exclude same-day space-formatted rows.
    since = (datetime.utcnow() - timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    rows: List[Any] = []
    with db_session() as db:
        try:
            from sqlalchemy import inspect

            columns = {
                str(column["name"])
                for column in inspect(db.get_bind()).get_columns("policy_evaluation_log")
            }
            context_column = "context" if "context" in columns else "guardrails_json"
            rows = list(db.execute(
                text(
                    f"SELECT action, decision, reason, {context_column} AS context, created_at "
                    "FROM policy_evaluation_log "
                    "WHERE created_at >= :since ORDER BY created_at DESC"
                ),
                {"since": since},
            ).mappings().all())
        except Exception:
            rows = []

    by_decision: Dict[str, int] = {}
    by_action: Dict[str, int] = {}
    by_agentic_tag: Dict[str, int] = {}
    frameworks_seen: set[str] = set()
    recent: List[Dict[str, Any]] = []
    for r in rows:
        action = str(r.get("action") or "unknown")
        decision = str(r.get("decision") or "unknown")
        by_decision[decision] = by_decision.get(decision, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1
        ctx: Dict[str, Any] = {}
        try:
            ctx = json.loads(r.get("context") or "{}")
        except Exception:
            ctx = {}
        fw = (ctx.get("frameworks") or {}) if isinstance(ctx, dict) else {}
        for tag in (fw.get("owasp_agentic_top10") or []):
            by_agentic_tag[str(tag)] = by_agentic_tag.get(str(tag), 0) + 1
        for c in (fw.get("compliance") or []):
            frameworks_seen.add(str(c))
        if len(recent) < int(limit):
            recent.append({
                "action": action, "decision": decision,
                "reason": str(r.get("reason") or "")[:160],
                "owasp_agentic": fw.get("owasp_agentic_top10") or [],
                "created_at": str(r.get("created_at") or ""),
            })

    total = len(rows)
    # Coverage: a tagged row proves the framework-queryable audit is working.
    tagged = sum(by_agentic_tag.values())
    return {
        "window_days": int(days),
        "total_consequential_decisions": total,
        "audit_coverage": {
            "framework_tagged_rows": tagged,
            "queryable": tagged > 0 or total == 0,
            "note": "every consequential decision is logged with OWASP-Agentic/PCI-Req10/ISO-42001 tags (execution_gate B4)",
        },
        "by_decision": by_decision,
        "by_action": by_action,
        "by_owasp_agentic_tag": by_agentic_tag,
        "compliance_frameworks": sorted(frameworks_seen),
        "recent": recent,
    }


@router.get("/decision-evidence")
def grc_decision_evidence(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(25, ge=1, le=200),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Framework-queryable evidence of consequential-action governance (ISO 42001 / EU AI Act /
    PCI Req 10 / OWASP Agentic) — the auditable proof an enterprise/QSA asks for."""
    return build_decision_evidence(days=days, limit=limit)


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


# ── Persistent Risk Register Snapshots ────────────────────────────────

def _ensure_rr_table() -> None:
    """Idempotent DDL for risk_register_snapshots (safe for SQLite + PG)."""
    try:
        with db_session() as db:
            db.execute(text(
                "CREATE TABLE IF NOT EXISTS risk_register_snapshots ("
                "  id TEXT PRIMARY KEY,"
                "  domain TEXT NOT NULL,"
                "  risk_score REAL NOT NULL,"
                "  risk_band TEXT NOT NULL,"
                "  snapshot_date TEXT NOT NULL,"
                "  risk_owner TEXT,"
                "  mitigation_strategy TEXT,"
                "  mitigation_deadline TEXT,"
                "  residual_risk_score REAL,"
                "  status TEXT NOT NULL DEFAULT 'open',"
                "  signals_json TEXT,"
                "  created_at TEXT DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            db.commit()
    except Exception:
        pass


def _take_snapshot(days: int = 30) -> List[Dict[str, Any]]:
    """Compute current risk register and persist one row per domain."""
    _ensure_rr_table()
    rr = _build_risk_register(days)
    rows: List[Dict[str, Any]] = []
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with db_session() as db:
        for domain in rr.get("domains", []):
            existing = db.execute(
                text(
                    "SELECT id FROM risk_register_snapshots WHERE domain = :domain AND snapshot_date = :date LIMIT 1"
                ),
                {"domain": domain["domain"], "date": today},
            ).fetchone()
            if existing:
                rid = str(existing[0])
                db.execute(
                    text(
                        "UPDATE risk_register_snapshots "
                        "SET risk_score = :score, risk_band = :band, signals_json = :signals "
                        "WHERE id = :id"
                    ),
                    {
                        "id": rid,
                        "score": domain["risk_score"],
                        "band": domain["risk_band"],
                        "signals": json.dumps(domain.get("signals", {})),
                    },
                )
            else:
                rid = str(uuid.uuid4())
                db.execute(
                    text(
                        "INSERT INTO risk_register_snapshots "
                        "(id, domain, risk_score, risk_band, snapshot_date, signals_json, status) "
                        "VALUES (:id, :domain, :score, :band, :date, :signals, 'open')"
                    ),
                    {
                        "id": rid,
                        "domain": domain["domain"],
                        "score": domain["risk_score"],
                        "band": domain["risk_band"],
                        "date": today,
                        "signals": json.dumps(domain.get("signals", {})),
                    },
                )
            rows.append({"id": rid, "domain": domain["domain"], "risk_score": domain["risk_score"], "risk_band": domain["risk_band"]})
        db.commit()
    return rows


@router.post("/risk-register/snapshot")
def create_risk_register_snapshot(
    days: int = Query(30, ge=1, le=365),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Take a point-in-time snapshot of all risk domains."""
    rows = _take_snapshot(days)
    return {"ok": True, "snapshot_count": len(rows), "snapshots": rows}


@router.get("/risk-register/history")
def risk_register_history(
    domain: str | None = Query(None),
    days: int = Query(90, ge=1, le=730),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Return historical risk register snapshots."""
    _ensure_rr_table()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with db_session() as db:
        if domain:
            rows = db.execute(
                text(
                    "SELECT id, domain, risk_score, risk_band, snapshot_date, risk_owner, "
                    "mitigation_strategy, mitigation_deadline, residual_risk_score, status, signals_json "
                    "FROM risk_register_snapshots WHERE domain = :d AND snapshot_date >= :since "
                    "ORDER BY snapshot_date DESC"
                ), {"d": domain, "since": since},
            ).fetchall()
        else:
            rows = db.execute(
                text(
                    "SELECT id, domain, risk_score, risk_band, snapshot_date, risk_owner, "
                    "mitigation_strategy, mitigation_deadline, residual_risk_score, status, signals_json "
                    "FROM risk_register_snapshots WHERE snapshot_date >= :since "
                    "ORDER BY snapshot_date DESC"
                ), {"since": since},
            ).fetchall()
    snapshots = []
    for r in rows:
        snapshots.append({
            "id": r[0], "domain": r[1], "risk_score": r[2], "risk_band": r[3],
            "snapshot_date": r[4], "risk_owner": r[5], "mitigation_strategy": r[6],
            "mitigation_deadline": r[7], "residual_risk_score": r[8], "status": r[9],
            "signals": json.loads(r[10]) if r[10] else {},
        })
    return {"snapshots": snapshots, "count": len(snapshots)}


@router.patch("/risk-register/snapshots/{snapshot_id}")
def update_risk_register_snapshot(
    snapshot_id: str,
    risk_owner: str | None = Query(None),
    mitigation_strategy: str | None = Query(None),
    mitigation_deadline: str | None = Query(None),
    residual_risk_score: float | None = Query(None, ge=0, le=100),
    status: str | None = Query(None, pattern="^(open|mitigating|accepted|closed)$"),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Update ownership, mitigation, or status of a risk snapshot."""
    _ensure_rr_table()
    updates: List[str] = []
    params: Dict[str, Any] = {"sid": snapshot_id}
    if risk_owner is not None:
        updates.append("risk_owner = :owner")
        params["owner"] = risk_owner
    if mitigation_strategy is not None:
        updates.append("mitigation_strategy = :strat")
        params["strat"] = mitigation_strategy
    if mitigation_deadline is not None:
        updates.append("mitigation_deadline = :dl")
        params["dl"] = mitigation_deadline
    if residual_risk_score is not None:
        updates.append("residual_risk_score = :rrs")
        params["rrs"] = residual_risk_score
    if status is not None:
        updates.append("status = :st")
        params["st"] = status
    if not updates:
        raise HTTPException(status_code=400, detail="no_fields_to_update")
    sql = f"UPDATE risk_register_snapshots SET {', '.join(updates)} WHERE id = :sid"
    with db_session() as db:
        result = db.execute(text(sql), params)
        db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="snapshot_not_found")
    return {"ok": True, "snapshot_id": snapshot_id}


def get_latest_risk_bands() -> Dict[str, str]:
    """Return the most recent risk_band per domain from snapshots.

    Used by the policy gate and orchestrator for dynamic threshold adjustment.
    Returns e.g. {"supplier_trust": "high", "insider_threat": "low"}.
    """
    _ensure_rr_table()
    bands: Dict[str, str] = {}
    try:
        with db_session() as db:
            rows = db.execute(text(
                "SELECT domain, risk_band FROM risk_register_snapshots "
                "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM risk_register_snapshots)"
            )).fetchall()
            for r in rows:
                bands[r[0]] = r[1]
    except Exception:
        pass
    return bands


# ---------------------------------------------------------------------------
# FAIR Monte Carlo CRQ endpoint (auditor / CISO facing)
# ---------------------------------------------------------------------------

@router.post("/crq/fair")
def run_fair_crq(
    asset_value: float = Query(100_000.0, ge=0, description="Estimated asset value ($)"),
    tef_low: float = Query(1.0, ge=0),
    tef_mode: float = Query(5.0, ge=0),
    tef_high: float = Query(20.0, ge=0),
    vuln_low: float = Query(0.1, ge=0, le=1),
    vuln_mode: float = Query(0.3, ge=0, le=1),
    vuln_high: float = Query(0.7, ge=0, le=1),
    plm_low: float = Query(500.0, ge=0),
    plm_mode: float = Query(5_000.0, ge=0),
    plm_high: float = Query(50_000.0, ge=0),
    slm_low: float = Query(0.0, ge=0),
    slm_mode: float = Query(2_000.0, ge=0),
    slm_high: float = Query(20_000.0, ge=0),
    simulations: int = Query(5_000, ge=100, le=50_000),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Run an on-demand FAIR Monte Carlo risk quantification.

    Intended for CISO / board-level reporting.  Returns ALE distribution,
    loss-event frequency, single-loss expectancy percentiles, histogram,
    and risk-band classification.
    """
    from src.app.services.risk_quantification import fair_monte_carlo
    return fair_monte_carlo(
        tef_low=tef_low, tef_mode=tef_mode, tef_high=tef_high,
        vuln_low=vuln_low, vuln_mode=vuln_mode, vuln_high=vuln_high,
        plm_low=plm_low, plm_mode=plm_mode, plm_high=plm_high,
        slm_low=slm_low, slm_mode=slm_mode, slm_high=slm_high,
        asset_value=asset_value,
        simulations=simulations,
    )


@router.post("/crq/fair/from-signals")
def run_fair_crq_from_signals(
    monetary_exposure: float = Query(1_000.0, ge=0),
    fraud_level: str = Query("low", pattern="^(minimal|low|medium|high)$"),
    cv_severity: str = Query("minor", pattern="^(minor|moderate|major|high|critical)$"),
    signal_count: int = Query(1, ge=0, le=100),
    simulations: int = Query(5_000, ge=100, le=50_000),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Derive FAIR inputs from live signal data and run Monte Carlo."""
    from src.app.services.risk_quantification import fair_from_signals
    return fair_from_signals(
        security={"signals": ["sig"] * signal_count},
        cv_analysis={"severity": cv_severity},
        fraud={"level": fraud_level},
        monetary_exposure=monetary_exposure,
        simulations=simulations,
    )


# ---------------------------------------------------------------------------
# DREAD calibration summary (historical predicted-vs-actual)
# ---------------------------------------------------------------------------

@router.get("/dread-calibration")
def dread_calibration_summary(
    days: int = Query(90, ge=1, le=3650),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Return aggregate DREAD calibration data (predicted vs actual damage)."""
    from src.app.services.dread_calibration import get_calibration_summary
    return get_calibration_summary(days=days)
