from __future__ import annotations

import ipaddress
import json
import os
import re
import uuid
from typing import Any, Dict, List


_HOST_RE = re.compile(r"^[a-z0-9.-]+$", re.IGNORECASE)


def _csv_env(name: str) -> list[str]:
    return [x.strip() for x in str(os.getenv(name, "") or "").split(",") if x.strip()]


def _host_allowed(host: str) -> bool:
    host_n = str(host or "").strip().lower()
    if not host_n:
        return False
    allow_hosts = [h.lower() for h in _csv_env("VULN_SCAN_ALLOWED_HOSTS")]
    allow_suffixes = [s.lower() for s in _csv_env("VULN_SCAN_ALLOWED_SUFFIXES")]
    allow_cidrs = _csv_env("VULN_SCAN_ALLOWED_CIDRS")
    if host_n in allow_hosts:
        return True
    if any(host_n.endswith(sfx) for sfx in allow_suffixes):
        return True
    try:
        ip = ipaddress.ip_address(host_n)
        for c in allow_cidrs:
            try:
                if ip in ipaddress.ip_network(c, strict=False):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _normalize_targets(targets: List[str] | None) -> list[str]:
    out: list[str] = []
    seen = set()
    for t in (targets or []):
        x = str(t or "").strip().lower()
        if not x or x in seen:
            continue
        if not _HOST_RE.match(x):
            continue
        out.append(x)
        seen.add(x)
    return out[:200]


def evaluate_scan_scope(*, targets: List[str] | None, tenant_id: str | None) -> Dict[str, Any]:
    normalized = _normalize_targets(targets)
    denied = [t for t in normalized if not _host_allowed(t)]
    allowed = [t for t in normalized if _host_allowed(t)]
    return {
        "tenant_id": str(tenant_id or "") or None,
        "allowed_targets": allowed,
        "denied_targets": denied,
        "allowed_count": len(allowed),
        "denied_count": len(denied),
        "scope_allowed": len(allowed) > 0 and len(denied) == 0,
    }


def run_vulnerability_scan(  # noqa: C901  (kept for security_integrations.py caller; migrate to routers/vuln_scan.py POST /api/v1/security/scan/full)
    *,
    tenant_id: str | None,
    targets: List[str] | None,
    profile: str = "baseline",
    provider: str | None = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    scope = evaluate_scan_scope(targets=targets, tenant_id=tenant_id)
    if not scope.get("scope_allowed"):
        return {
            "ok": False,
            "reason": "scan_scope_denied",
            "scope": scope,
            "findings": [],
        }

    provider_n = str(provider or os.getenv("VULN_SCAN_PROVIDER", "service")).strip().lower()
    profile_n = str(profile or "baseline").strip().lower()
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "provider": provider_n,
            "profile": profile_n,
            "scope": scope,
            "findings": [],
            "commands": [f"{provider_n} scan --profile {profile_n} --target {t}" for t in scope["allowed_targets"][:10]],
        }

    findings: list[dict[str, Any]] = []
    if provider_n in ("service", "vuln_scanner"):
        import asyncio

        from src.app.services.vuln_scanner import VulnScanService

        async def _run() -> list[dict[str, Any]]:
            svc = VulnScanService()
            out: list[dict[str, Any]] = []
            for target in scope["allowed_targets"]:
                report = await svc.scan_all(target_url=f"https://{target}")
                for finding in report.findings:
                    out.append(
                        {
                            "target": target,
                            "id": getattr(finding, "cve_id", None) or getattr(finding, "title", "finding"),
                            "severity": getattr(finding, "severity", "info"),
                            "title": getattr(finding, "title", "Vulnerability finding"),
                            "confidence": round(float(getattr(finding, "cvss_score", 0.0) or 0.0) / 10.0, 4),
                            "plain_english": getattr(finding, "plain_english", ""),
                            "source": getattr(finding, "source", "service"),
                        }
                    )
            return out

        findings = asyncio.run(_run())
    elif provider_n in ("nuclei", "openvas"):
        # DEPRECATED: direct subprocess invocation. Prefer provider="service" which delegates
        # to VulnScanService (routers/vuln_scan.py). This path will be removed once
        # security_integrations.py caller is updated to use the dedicated scan router.
        import shutil, subprocess, tempfile
        binary_name = os.getenv("VULN_SCAN_BINARY") or provider_n
        binary_path = shutil.which(binary_name)
        if not binary_path:
            return {
                "ok": False,
                "reason": "provider_binary_not_found",
                "provider": provider_n,
                "hint": f"Install {provider_n} and ensure it is on PATH, or set VULN_SCAN_BINARY env var.",
                "scope": scope,
                "findings": [],
            }
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                out_path = tmp.name
            cmd = [binary_path, "-l", ",".join(scope["allowed_targets"]), "-json", "-o", out_path]
            if profile_n and profile_n != "baseline":
                cmd += ["-t", profile_n]
            result_proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result_proc.returncode == 0:
                import json as _json
                with open(out_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            row = _json.loads(line.strip())
                            findings.append({
                                "target": row.get("host") or row.get("ip"),
                                "id": row.get("template-id") or row.get("info", {}).get("id"),
                                "severity": (row.get("info", {}).get("severity") or "info").lower(),
                                "title": row.get("info", {}).get("name") or row.get("matched-at"),
                                "confidence": 0.9,
                                "raw": row,
                            })
                        except Exception:
                            continue
            else:
                return {"ok": False, "reason": "provider_execution_failed", "stderr": result_proc.stderr[:500], "scope": scope, "findings": []}
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "provider_timeout", "scope": scope, "findings": []}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)[:200], "scope": scope, "findings": []}
    return {
        "ok": True,
        "dry_run": False,
        "provider": provider_n,
        "profile": profile_n,
        "scope": scope,
        "finding_count": len(findings),
        "findings": findings[:500],
        "requires_security_review": any(str(f.get("severity")) in ("high", "critical") for f in findings),
    }


# ---------------------------------------------------------------------------
# CVSS severity mapping
# ---------------------------------------------------------------------------
_SEVERITY_TO_CVSS: Dict[str, float] = {
    "critical": 9.5,
    "high": 8.0,
    "medium": 5.5,
    "low": 2.5,
    "info": 0.0,
}


def severity_to_cvss(severity: str) -> float:
    """Map a severity label to a representative CVSS v3 score."""
    return _SEVERITY_TO_CVSS.get(str(severity or "").strip().lower(), 0.0)


def auto_create_incidents_from_findings(
    *,
    scan_result: Dict[str, Any],
    tenant_id: str | None = None,
    trace_id: str | None = None,
    cvss_threshold: float = 7.0,
) -> List[Dict[str, Any]]:
    """Automatically create incident records for findings above CVSS threshold.

    Returns a list of created incident dicts [{incident_id, finding_id, severity, cvss, ...}].
    Only creates incidents for findings with CVSS >= cvss_threshold (default 7.0 = high+critical).
    """
    findings = scan_result.get("findings") or []
    created: List[Dict[str, Any]] = []

    for finding in findings:
        sev = str(finding.get("severity") or "").lower()
        cvss = severity_to_cvss(sev)
        if cvss < cvss_threshold:
            continue

        incident_id = str(uuid.uuid4())
        incident = {
            "incident_id": incident_id,
            "finding_id": finding.get("id"),
            "target": finding.get("target"),
            "title": finding.get("title") or "Vulnerability finding",
            "severity": sev,
            "cvss_score": cvss,
            "confidence": finding.get("confidence"),
            "tenant_id": tenant_id,
            "trace_id": trace_id,
            "auto_created": True,
            "status": "open",
        }

        # Persist to DB (best-effort)
        try:
            from src.app.models.db import db_session
            from sqlalchemy import text as sql_text
            with db_session() as db:
                db.execute(
                    sql_text(
                        "INSERT INTO incidents (id, title, description, severity, status, tenant_id, trace_id) "
                        "VALUES (:id, :title, :desc, :sev, :status, :tid, :trid)"
                    ),
                    {
                        "id": incident_id,
                        "title": f"[CVSS {cvss}] {incident['title']} on {incident['target']}",
                        "desc": json.dumps(finding, ensure_ascii=False, default=str),
                        "sev": sev,
                        "status": "open",
                        "tid": tenant_id,
                        "trid": trace_id,
                    },
                )
                db.commit()
        except Exception:
            pass  # DB may not have incidents table; incident dict still returned

        created.append(incident)

    return created
