"""Vulnerability scanning service.

Orchestrates multiple scanners in priority order, all optional:
  - Trivy      — container/SBOM scanning (local binary)
  - Nuclei     — web application scanning (local binary, opt-in via VULN_SCAN_WEB_ENABLED)
  - Semgrep    — SAST code scanning (local binary)
  - CISA KEV   — Known Exploited Vulnerabilities catalog (free HTTPS, no key)

All scanners degrade gracefully: if the binary is not installed, the scan
is skipped and an informational note is added to `report.errors`.

Usage:
    svc = VulnScanService()
    report = await svc.scan_all(target_url="https://mystore.example.com",
                                image_ref="mystore:latest",
                                code_path="/app/src")
    print(report.merchant_summary())
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.config import get_settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class VulnFinding:
    cve_id: Optional[str]
    cvss_score: float
    severity: str           # critical / high / medium / low / informational
    package: Optional[str]
    installed_version: Optional[str]
    fixed_version: Optional[str]
    title: str
    description: str
    plain_english: str      # non-technical, merchant-readable sentence
    source: str             # trivy / nuclei / semgrep / cisa_kev
    kev_match: bool = False          # True if CVE is in CISA KEV catalog
    kev_date_added: Optional[str] = None  # ISO date CVE was added to KEV
    kev_due_date: Optional[str] = None    # CISA required remediation date


@dataclass
class VulnReport:
    scan_id: str
    target: str
    findings: List[VulnFinding] = field(default_factory=list)
    risk_score: float = 0.0   # 0.0 – 10.0
    scorecard: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    def merchant_summary(self) -> str:
        """Plain-English paragraph suitable for the merchant dashboard."""
        if not self.findings:
            return "No known vulnerabilities found. Your dependencies and endpoints look clean."
        crit = self.critical_count
        high = self.high_count
        parts: List[str] = []
        if crit:
            parts.append(
                f"{crit} critical issue{'s' if crit > 1 else ''} requiring immediate patching"
            )
        if high:
            parts.append(
                f"{high} high-severity issue{'s' if high > 1 else ''} to address this week"
            )
        rest = len(self.findings) - crit - high
        if rest:
            parts.append(
                f"{rest} lower-priority finding{'s' if rest > 1 else ''} to review this month"
            )
        return (
            f"Security scan found {', '.join(parts)}. "
            f"Overall risk score: {self.risk_score:.1f}/10."
        )

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "risk_score": self.risk_score,
            "summary": self.merchant_summary(),
            "critical": self.critical_count,
            "high": self.high_count,
            "total_findings": len(self.findings),
            "top_actions": self.scorecard.get("top_actions", []),
            "sources_used": self.scorecard.get("sources_used", []),
            "scan_errors": self.errors,
            "findings": [
                {
                    "cve_id": f.cve_id,
                    "severity": f.severity,
                    "cvss_score": f.cvss_score,
                    "title": f.title,
                    "plain_english": f.plain_english,
                    "package": f.package,
                    "installed_version": f.installed_version,
                    "fix_version": f.fixed_version,
                    "source": f.source,
                }
                for f in self.findings
            ],
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class VulnScanService:
    """
    Lightweight async wrapper that runs available scanner binaries and
    aggregates findings into a VulnReport with plain-English output.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._trivy = shutil.which("trivy") is not None
        self._nuclei = shutil.which("nuclei") is not None
        self._semgrep = shutil.which("semgrep") is not None
        self._web_enabled = bool(settings.vuln_scan_web_enabled)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def scan_all(
        self,
        target_url: str = "",
        image_ref: str = "",
        code_path: str = "",
    ) -> VulnReport:
        report = VulnReport(
            scan_id=str(uuid.uuid4())[:8],
            target=target_url or image_ref or code_path or "unknown",
        )

        tasks: List[asyncio.Task] = []

        if image_ref:
            if self._trivy:
                tasks.append(asyncio.create_task(self._trivy_scan(image_ref, report)))
            else:
                report.errors.append(
                    "trivy not installed — container scan skipped. "
                    "Install: https://aquasecurity.github.io/trivy/"
                )

        if target_url and self._nuclei and self._web_enabled:
            tasks.append(asyncio.create_task(self._nuclei_scan(target_url, report)))
        elif target_url and not self._nuclei:
            report.errors.append(
                "nuclei not installed — web app scan skipped. "
                "Install: go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest"
            )
        elif target_url and not self._web_enabled:
            report.errors.append(
                "Web scanning disabled (VULN_SCAN_WEB_ENABLED=0). "
                "Set VULN_SCAN_WEB_ENABLED=1 to enable nuclei web scanning."
            )

        if code_path and self._semgrep:
            tasks.append(asyncio.create_task(self._semgrep_scan(code_path, report)))

        # CISA KEV runs after other scans to annotate findings with active-exploitation flag
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Annotate with CISA KEV (network call — best-effort)
        await self._annotate_cisa_kev(report)

        report.risk_score = _compute_risk_score(report.findings)
        report.scorecard = _build_scorecard(report)
        return report

    # ------------------------------------------------------------------
    # Trivy — container + SBOM
    # ------------------------------------------------------------------
    async def _trivy_scan(self, image_ref: str, report: VulnReport) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "trivy",
                "image",
                "--format", "json",
                "--quiet",
                "--timeout", "2m",
                image_ref,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=130)
            if proc.returncode not in (0, 1):
                report.errors.append(f"trivy exited {proc.returncode}: {stderr.decode()[:300]}")
                return
            data = json.loads(stdout)
            for result in data.get("Results", []):
                for vuln in result.get("Vulnerabilities") or []:
                    sev = (vuln.get("Severity") or "unknown").lower()
                    nvd = (vuln.get("CVSS") or {}).get("nvd") or {}
                    cvss = float(nvd.get("V3Score") or nvd.get("V2Score") or 0)
                    pkg = vuln.get("PkgName", "")
                    cve = vuln.get("VulnerabilityID", "")
                    fixed = vuln.get("FixedVersion", "")
                    title = vuln.get("Title") or cve or "Unknown vulnerability"
                    report.findings.append(VulnFinding(
                        cve_id=cve or None,
                        cvss_score=cvss,
                        severity=sev,
                        package=pkg or None,
                        installed_version=vuln.get("InstalledVersion"),
                        fixed_version=fixed or None,
                        title=title,
                        description=(vuln.get("Description") or "")[:300],
                        plain_english=_trivy_plain_english(pkg, cve, sev, fixed),
                        source="trivy",
                    ))
        except asyncio.TimeoutError:
            report.errors.append("trivy scan timed out after 2 minutes")
        except Exception as exc:
            log.warning("trivy scan error: %s", exc)
            report.errors.append(f"trivy scan error: {exc}")

    # ------------------------------------------------------------------
    # Nuclei — web application
    # ------------------------------------------------------------------
    async def _nuclei_scan(self, target_url: str, report: VulnReport) -> None:
        templates = get_settings().nuclei_templates_path or os.path.expanduser("~/.local/nuclei-templates")
        args = [
            "nuclei",
            "-u", target_url,
            "-json",
            "-silent",
            "-rate-limit", "10",
        ]
        if os.path.isdir(templates):
            args += ["-t", templates]
        else:
            # Fallback: use built-in templates
            args += ["-t", "cves", "-t", "exposures", "-t", "misconfiguration"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=200)
            for line in stdout.decode(errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                info = item.get("info") or {}
                sev = (info.get("severity") or "informational").lower()
                classification = info.get("classification") or {}
                cvss = float(classification.get("cvss-score") or 0)
                cve_ids: List[str] = classification.get("cve-id") or []
                cve = cve_ids[0] if cve_ids else None
                name = info.get("name") or item.get("template-id") or ""
                matched_at = item.get("matched-at") or target_url
                report.findings.append(VulnFinding(
                    cve_id=cve,
                    cvss_score=cvss,
                    severity=sev,
                    package=None,
                    installed_version=None,
                    fixed_version=None,
                    title=name,
                    description=(info.get("description") or "")[:300],
                    plain_english=_nuclei_plain_english(name, sev, matched_at),
                    source="nuclei",
                ))
        except asyncio.TimeoutError:
            report.errors.append("nuclei scan timed out after 3 minutes")
        except Exception as exc:
            log.warning("nuclei scan error: %s", exc)
            report.errors.append(f"nuclei scan error: {exc}")

    # ------------------------------------------------------------------
    # Semgrep — SAST
    # ------------------------------------------------------------------
    async def _semgrep_scan(self, code_path: str, report: VulnReport) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "semgrep",
                "--config=p/owasp-top-ten",
                "--config=p/python",
                "--json",
                "--quiet",
                code_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=100)
            data = json.loads(stdout)
            for result in data.get("results") or []:
                extra = result.get("extra") or {}
                raw_sev = (extra.get("severity") or "WARNING").lower()
                sev = {"error": "high", "warning": "medium", "info": "low"}.get(raw_sev, "low")
                path = result.get("path") or ""
                line = (result.get("start") or {}).get("line", "?")
                check_id = result.get("check_id") or ""
                message = (extra.get("message") or "")[:300]
                report.findings.append(VulnFinding(
                    cve_id=None,
                    cvss_score=0.0,
                    severity=sev,
                    package=path,
                    installed_version=f"line {line}",
                    fixed_version=None,
                    title=check_id,
                    description=message,
                    plain_english=f"Potential {sev}-severity security issue in {path} (line {line}): {message[:120]}",
                    source="semgrep",
                ))
        except asyncio.TimeoutError:
            report.errors.append("semgrep scan timed out after 100 seconds")
        except Exception as exc:
            log.warning("semgrep scan error: %s", exc)
            report.errors.append(f"semgrep scan error: {exc}")

    # ------------------------------------------------------------------
    # CISA KEV annotation (free, no API key)
    # ------------------------------------------------------------------
    async def _annotate_cisa_kev(self, report: VulnReport) -> None:
        """Annotate findings that appear in the CISA Known Exploited Vulnerabilities catalog.

        Sets kev_match=True, kev_date_added, kev_due_date, promotes severity to critical,
        and prepends an "ACTIVELY EXPLOITED" prefix to plain_english.

        Tries local data/cisa_kev.json first (for offline/test environments), then falls
        back to the live CISA feed.
        """
        cve_findings = {f.cve_id: f for f in report.findings if f.cve_id}
        if not cve_findings:
            return

        kev_lookup: Dict[str, Dict[str, str]] = {}  # cveID → {dateAdded, dueDate}

        # ── 1. Try local KEV snapshot ──
        _local_paths = [
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "cisa_kev.json"),
            os.path.join(os.getcwd(), "data", "cisa_kev.json"),
        ]
        _local_loaded = False
        for _lp in _local_paths:
            try:
                with open(os.path.normpath(_lp), "r", encoding="utf-8") as _f:
                    _local_kev = json.load(_f)
                for _v in _local_kev.get("vulnerabilities", []):
                    if _v.get("cveID"):
                        kev_lookup[_v["cveID"]] = {
                            "dateAdded": _v.get("dateAdded", ""),
                            "dueDate": _v.get("dueDate", ""),
                        }
                _local_loaded = True
                break
            except Exception:
                continue

        # ── 2. Live feed fallback (skipped when local loaded and not stale) ──
        _kev_ttl_hours = max(1, int(os.getenv("CISA_KEV_CACHE_TTL_HOURS", "24") or 24))
        _live_enabled = _truthy("CISA_KEV_LIVE_FETCH_ENABLED", "1")
        if not _local_loaded and _live_enabled:
            try:
                import httpx  # type: ignore
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(
                        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
                    )
                    resp.raise_for_status()
                    _live_vulns = resp.json().get("vulnerabilities", [])
                for _v in _live_vulns:
                    if _v.get("cveID"):
                        kev_lookup[_v["cveID"]] = {
                            "dateAdded": _v.get("dateAdded", ""),
                            "dueDate": _v.get("dueDate", ""),
                        }
            except Exception as exc:
                log.debug("CISA KEV live fetch failed (non-fatal): %s", exc)
                report.errors.append(f"CISA KEV lookup failed (non-fatal): {exc}")

        # ── 3. Annotate matching findings ──
        for cve_id, finding in cve_findings.items():
            if cve_id in kev_lookup:
                _kev_meta = kev_lookup[cve_id]
                finding.kev_match = True
                finding.kev_date_added = _kev_meta.get("dateAdded") or None
                finding.kev_due_date = _kev_meta.get("dueDate") or None
                finding.severity = "critical"
                _due_note = (
                    f" CISA remediation deadline: {finding.kev_due_date}."
                    if finding.kev_due_date else ""
                )
                finding.plain_english = (
                    f"ACTIVELY EXPLOITED IN THE WILD: {finding.plain_english}"
                    f" This CVE is on the CISA Known Exploited Vulnerabilities list — patch immediately.{_due_note}"
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _trivy_plain_english(pkg: str, cve: str, severity: str, fixed: str) -> str:
    pkg_label = pkg or "a dependency"
    fix_note = f" Update to version {fixed}." if fixed else " No patch is available yet — consider isolation."
    return f"The {pkg_label} package has a {severity}-severity vulnerability ({cve}).{fix_note}"


def _nuclei_plain_english(name: str, severity: str, matched_at: str) -> str:
    return (
        f"{severity.capitalize()} security misconfiguration detected: {name}. "
        f"Found at: {matched_at}"
    )


def _compute_risk_score(findings: List[VulnFinding]) -> float:
    if not findings:
        return 0.0
    weights = {"critical": 10.0, "high": 7.0, "medium": 4.0, "low": 1.0, "informational": 0.2}
    score = sum(weights.get(f.severity, 1.0) * max(f.cvss_score / 10.0, 0.3) for f in findings)
    return min(round(score / max(len(findings), 1), 1), 10.0)


def _build_scorecard(report: VulnReport) -> Dict[str, Any]:
    critical = [f for f in report.findings if f.severity == "critical"]
    return {
        "risk_score": report.risk_score,
        "total_findings": len(report.findings),
        "critical": report.critical_count,
        "high": report.high_count,
        "medium": sum(1 for f in report.findings if f.severity == "medium"),
        "low": sum(1 for f in report.findings if f.severity == "low"),
        "sources_used": sorted({f.source for f in report.findings}),
        "summary": report.merchant_summary(),
        "top_actions": [
            f"Patch {f.package or 'component'}: {f.title[:80]}"
            for f in critical[:3]
        ],
    }
