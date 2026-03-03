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


def run_vulnerability_scan(
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

    provider_n = str(provider or os.getenv("VULN_SCAN_PROVIDER", "mock")).strip().lower()
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
    if provider_n in ("mock", "nuclei", "openvas"):
        for t in scope["allowed_targets"]:
            # deterministic synthetic severity until real provider adapter wiring.
            sev = "medium" if ("admin" in t or "api" in t) else "low"
            findings.append(
                {
                    "target": t,
                    "id": f"{provider_n.upper()}-{abs(hash((t, profile_n))) % 100000}",
                    "severity": sev,
                    "title": "Potential misconfiguration",
                    "confidence": 0.62 if sev == "medium" else 0.44,
                }
            )
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

