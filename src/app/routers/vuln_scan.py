"""Vulnerability scan API endpoints.

POST /api/v1/security/scan/full   — run full scan, return results
GET  /api/v1/security/scan/status — check scanner availability

Requires owner or developer role.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, HTTPException

from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/security/scan", tags=["security-scan"])
_WORKSPACE_ROOT = Path(os.getenv("VULN_SCAN_CODE_ROOT", os.getcwd())).resolve()


def _scan_enabled() -> bool:
    return os.getenv("VULN_SCAN_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def _resolve_scan_code_path(raw_path: str) -> str:
    candidate = Path(raw_path).expanduser()
    resolved = candidate.resolve(strict=False)
    if not resolved.is_absolute():
        raise HTTPException(status_code=422, detail="code_path must be an absolute path")
    try:
        resolved.relative_to(_WORKSPACE_ROOT)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"code_path must stay under approved root: {_WORKSPACE_ROOT}",
        ) from exc
    return str(resolved)


def _validate_target_url(target_url: str) -> str:
    parsed = urlparse(str(target_url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="target_url must be a valid http/https URL")
    return parsed.geturl()


@router.get("/status")
async def scan_status(
    _role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    """Return which scanner binaries are available on this host."""
    import shutil
    return {
        "vuln_scan_enabled": _scan_enabled(),
        "trivy_available": shutil.which("trivy") is not None,
        "nuclei_available": shutil.which("nuclei") is not None,
        "semgrep_available": shutil.which("semgrep") is not None,
        "web_scan_enabled": os.getenv("VULN_SCAN_WEB_ENABLED", "0").strip().lower()
        in ("1", "true", "yes", "on"),
        "install_hints": {
            "trivy": "https://aquasecurity.github.io/trivy/",
            "nuclei": "go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest",
            "semgrep": "pip install semgrep",
        },
        "approved_code_root": str(_WORKSPACE_ROOT),
    }


@router.post("/full")
async def run_full_scan(
    target_url: Optional[str] = Query(None, description="URL of the web app to scan (requires VULN_SCAN_WEB_ENABLED=1)"),
    image_ref: Optional[str] = Query(None, description="Docker image ref to scan with Trivy, e.g. mystore:latest"),
    code_path: Optional[str] = Query(None, description="Absolute path to source code for Semgrep SAST scan"),
    _role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    """
    Run a full vulnerability scan. All scanners are optional and degrade gracefully.

    - **target_url**: Nuclei web-app scan (requires VULN_SCAN_WEB_ENABLED=1 env var)
    - **image_ref**: Trivy container/SBOM scan
    - **code_path**: Semgrep SAST scan of local source code

    At least one of the three parameters must be provided.

    CISA Known Exploited Vulnerabilities (KEV) annotation runs automatically
    and promotes any actively-exploited CVEs to critical severity.
    """
    if not _scan_enabled():
        raise HTTPException(status_code=503, detail="Vulnerability scanning is disabled (VULN_SCAN_ENABLED=0).")

    if not any([target_url, image_ref, code_path]):
        raise HTTPException(
            status_code=422,
            detail="Provide at least one of: target_url, image_ref, or code_path.",
        )

    # Validate code_path is not outside the container to prevent path traversal
    if code_path:
        code_path = _resolve_scan_code_path(code_path)
    if target_url:
        target_url = _validate_target_url(target_url)

    from src.app.services.vuln_scanner import VulnScanService
    from src.app.security.dread_scorer import score_vuln_report
    svc = VulnScanService()
    report = await svc.scan_all(
        target_url=target_url or "",
        image_ref=image_ref or "",
        code_path=code_path or "",
    )
    dread = score_vuln_report(report)

    # Auto-escalate critical CVE findings to incidents (best-effort)
    if report.critical_count > 0:
        await _auto_escalate_critical(report)

    payload = report.to_api_dict()
    payload["dread"] = dread
    payload["approved_code_root"] = str(_WORKSPACE_ROOT)
    return payload


@router.get("/scorecard")
async def security_scorecard(
    tenant_id: Optional[str] = Query(None, description="Tenant to scope scorecard (omit for platform-wide)"),
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    _role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    """Return a merchant-facing security posture scorecard.

    Aggregates incident counts, severity distribution, and scan results over the
    requested lookback window.  All fields degrade gracefully if tables are absent.
    """
    from src.app.models.db import db_session
    from sqlalchemy import text as sql_text

    scorecard: dict = {
        "tenant_id": tenant_id,
        "window_days": days,
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }

    # --- incident counts ---
    try:
        with db_session() as db:
            base_filter = "created_at >= NOW() - INTERVAL ':d days'"
            params: dict = {"d": days}
            if tenant_id:
                rows = db.execute(
                    sql_text(
                        "SELECT severity, COUNT(*) FROM incidents "
                        "WHERE tenant_id = :tid AND created_at >= NOW() - :d * INTERVAL '1 day' "
                        "GROUP BY severity"
                    ),
                    {"tid": tenant_id, "d": days},
                ).fetchall()
            else:
                rows = db.execute(
                    sql_text(
                        "SELECT severity, COUNT(*) FROM incidents "
                        "WHERE created_at >= NOW() - :d * INTERVAL '1 day' GROUP BY severity"
                    ),
                    {"d": days},
                ).fetchall()
            counts: dict = {}
            total = 0
            for sev, cnt in rows:
                counts[str(sev)] = int(cnt)
                total += int(cnt)
            scorecard["incident_counts"] = counts
            scorecard["incident_total"] = total
    except Exception as exc:
        scorecard["incident_counts"] = {}
        scorecard["incident_total"] = 0
        scorecard["incident_counts_error"] = str(exc)[:120]

    # --- open critical/high incidents ---
    try:
        with db_session() as db:
            q_params: dict = {"d": days}
            if tenant_id:
                q_params["tid"] = tenant_id
                tid_clause = "AND tenant_id = :tid"
            else:
                tid_clause = ""
            rows = db.execute(
                sql_text(
                    f"SELECT id, title, severity, status, created_at FROM incidents "
                    f"WHERE severity IN ('critical','high') AND status = 'open' {tid_clause} "
                    f"AND created_at >= NOW() - :d * INTERVAL '1 day' "
                    f"ORDER BY created_at DESC LIMIT 10"
                ),
                q_params,
            ).mappings().fetchall()
            scorecard["open_critical_high"] = [
                {"id": r["id"], "title": r["title"], "severity": r["severity"], "created_at": str(r.get("created_at") or "")}
                for r in rows
            ]
    except Exception:
        scorecard["open_critical_high"] = []

    # --- last scan summary ---
    try:
        with db_session() as db:
            q_params: dict = {"d": days}
            if tenant_id:
                q_params["tid"] = tenant_id
                tid_clause = "WHERE tenant_id = :tid"
            else:
                tid_clause = ""
            rows = db.execute(
                sql_text(
                    f"SELECT target, risk_score, total_findings, critical_count, high_count, created_at "
                    f"FROM security_scan_scorecards {tid_clause} "
                    f"ORDER BY created_at DESC LIMIT 5"
                ),
                q_params,
            ).mappings().fetchall()
            scorecard["recent_scans"] = [
                {
                    "target": r.get("target"),
                    "risk_score": float(r.get("risk_score") or 0.0),
                    "total_findings": int(r.get("total_findings") or 0),
                    "critical": int(r.get("critical_count") or 0),
                    "high": int(r.get("high_count") or 0),
                    "created_at": str(r.get("created_at") or ""),
                }
                for r in rows
            ]
        from src.app.services.vuln_scanner import VulnScanService
        svc = VulnScanService()
        scorecard["scanner_available"] = True
        scorecard["trivy_available"] = __import__("shutil").which("trivy") is not None
        scorecard["semgrep_available"] = __import__("shutil").which("semgrep") is not None
        scorecard["nuclei_available"] = __import__("shutil").which("nuclei") is not None
    except Exception:
        scorecard["scanner_available"] = False
        scorecard["recent_scans"] = []

    # --- posture grade ---
    critical_open = sum(1 for i in scorecard.get("open_critical_high", []) if i.get("severity") == "critical")
    high_open = sum(1 for i in scorecard.get("open_critical_high", []) if i.get("severity") == "high")
    if critical_open >= 3:
        grade = "F"
    elif critical_open >= 1:
        grade = "D"
    elif high_open >= 3:
        grade = "C"
    elif high_open >= 1:
        grade = "B"
    else:
        grade = "A"
    scorecard["posture_grade"] = grade
    scorecard["posture_summary"] = (
        f"Grade {grade}: {critical_open} critical + {high_open} high open incidents "
        f"in the last {days} days."
    )
    return scorecard


async def _auto_escalate_critical(report) -> None:
    """Create incidents for critical CVE findings. Non-fatal on error."""
    try:
        from src.app.routers.escalation_room import create_incident_record

        critical = [f for f in report.findings if f.severity == "critical" and f.cve_id][:5]
        for finding in critical:
            await asyncio.to_thread(
                create_incident_record,
                case_id=str(finding.cve_id or finding.title or "vuln-critical")[:64],
                trace_id=None,
                reason="critical_vulnerability_detected",
                context={
                    "source": "vuln_scanner",
                    "cve_id": finding.cve_id,
                    "cvss_score": finding.cvss_score,
                    "package": finding.package,
                    "plain_english": finding.plain_english,
                },
                created_by="vuln_scanner",
                severity="critical",
                title=f"Critical CVE: {finding.cve_id or finding.title}",
                dedupe_by_event=True,
            )
    except Exception as exc:
        log.debug("auto-escalate critical CVE failed (non-fatal): %s", exc)
