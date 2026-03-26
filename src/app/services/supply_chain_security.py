"""Supply chain security scanner.

Detects three classes of supply-chain attack that target Python packages
consumed by the ShopSquire platform:

1. Typosquatting — package names that are common misspellings of popular
   packages (e.g. "reqeusts" vs "requests").

2. CISA KEV cross-reference — packages in requirements.txt that have active
   CVEs in the CISA Known Exploited Vulnerabilities catalog.

3. Dependency confusion — internal package names that also appear on PyPI
   (attacker publishes a malicious public version with a higher version number).

Results are logged, emitted as decision trace events, and turned into tickets
when severity is critical.

Usage:
    from src.app.services.supply_chain_security import run_supply_chain_scan
    report = await run_supply_chain_scan()
    print(report.to_dict())
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known typosquatting targets (canonical name → known misspellings)
# ---------------------------------------------------------------------------
_TYPOSQUAT_MAP: Dict[str, List[str]] = {
    "requests":     ["reqeusts", "requets", "reuqests", "request"],
    "fastapi":      ["fast-api", "fastpi", "fastapii"],
    "sqlalchemy":   ["sql-alchemy", "sqlalchmy", "sqalchemy"],
    "pydantic":     ["pydandic", "pydantics"],
    "uvicorn":      ["uvicron", "uvicorm"],
    "httpx":        ["httxp", "htpx"],
    "cryptography": ["cryptograpy", "criptography"],
    "paramiko":     ["paramiko2", "parramiko"],
    "boto3":        ["botto3", "bot03"],
    "pillow":       ["pilow", "pillow2"],
    "numpy":        ["numpyy", "num-py"],
    "pandas":       ["panas", "pandass"],
    "setuptools":   ["setuptool", "setup-tools"],
    "pip":          ["piip", "pipp"],
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SupplyChainFinding:
    package: str
    attack_type: str    # typosquatting / dependency_confusion / cisa_kev
    severity: str       # critical / high / medium / low
    detail: str
    cve_id: Optional[str] = None
    mitigation: str = ""


@dataclass
class SupplyChainScanReport:
    findings: List[SupplyChainFinding] = field(default_factory=list)
    scanned_packages: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    scanned_at: float = field(default_factory=time.time)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scanned_count": len(self.scanned_packages),
            "finding_count": len(self.findings),
            "critical_count": self.critical_count,
            "scanned_at": self.scanned_at,
            "findings": [
                {
                    "package": f.package,
                    "attack_type": f.attack_type,
                    "severity": f.severity,
                    "detail": f.detail,
                    "cve_id": f.cve_id,
                    "mitigation": f.mitigation,
                }
                for f in self.findings
            ],
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Package list extraction
# ---------------------------------------------------------------------------

def _parse_requirements(path: Path) -> List[str]:
    names: List[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
            if m:
                names.append(m.group(1).lower().replace("_", "-"))
    except Exception as exc:
        log.debug("supply_chain_security: could not parse %s: %s", path, exc)
    return names


def collect_packages(repo_root: Path) -> List[str]:
    """Return deduplicated package names from all requirements*.txt files."""
    packages: List[str] = []
    seen: set = set()
    for req_file in sorted(repo_root.glob("requirements*.txt")):
        for pkg in _parse_requirements(req_file):
            if pkg not in seen:
                seen.add(pkg)
                packages.append(pkg)
    return packages


# ---------------------------------------------------------------------------
# Typosquatting detector (pure in-process, no network)
# ---------------------------------------------------------------------------

def check_typosquatting(packages: List[str]) -> List[SupplyChainFinding]:
    findings: List[SupplyChainFinding] = []
    for pkg in packages:
        for legit, misspellings in _TYPOSQUAT_MAP.items():
            if pkg in misspellings:
                findings.append(SupplyChainFinding(
                    package=pkg,
                    attack_type="typosquatting",
                    severity="high",
                    detail=f"'{pkg}' is a known typosquat of '{legit}'",
                    mitigation=f"Replace '{pkg}' with '{legit}' in requirements.txt",
                ))
    return findings


# ---------------------------------------------------------------------------
# CISA KEV cross-reference (one HTTPS call, cached 24h)
# ---------------------------------------------------------------------------

_KEV_CATALOG: Optional[Dict[str, Any]] = None
_KEV_FETCHED_AT: float = 0.0
_KEV_TTL = 86_400.0  # 24 hours


async def _get_kev_catalog() -> List[Dict]:
    global _KEV_CATALOG, _KEV_FETCHED_AT
    now = time.time()
    if _KEV_CATALOG and (now - _KEV_FETCHED_AT) < _KEV_TTL:
        return _KEV_CATALOG.get("vulnerabilities") or []
    kev_url = os.getenv(
        "CISA_KEV_URL",
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(kev_url)
            r.raise_for_status()
            _KEV_CATALOG = r.json()
            _KEV_FETCHED_AT = now
            return _KEV_CATALOG.get("vulnerabilities") or []
    except Exception as exc:
        log.warning("supply_chain_security: CISA KEV fetch failed: %s", exc)
        return []


async def check_cisa_kev(packages: List[str]) -> List[SupplyChainFinding]:
    findings: List[SupplyChainFinding] = []
    vulns = await _get_kev_catalog()
    if not vulns:
        return findings

    # Build product→CVE lookup (lower-case)
    product_map: Dict[str, List[Dict]] = {}
    for v in vulns:
        for key in (v.get("product", ""), v.get("vendorProject", "")):
            k = str(key).lower().replace(" ", "-")
            if k:
                product_map.setdefault(k, []).append(v)

    for pkg in packages:
        matches = product_map.get(pkg, [])
        for v in matches[:2]:  # max 2 CVEs per package to avoid noise
            findings.append(SupplyChainFinding(
                package=pkg,
                attack_type="cisa_kev",
                severity="critical",
                detail=(
                    f"{v.get('cveID', '?')} — {v.get('vulnerabilityName', '')} "
                    f"(CISA due: {v.get('dueDate', 'unknown')})"
                ),
                cve_id=v.get("cveID"),
                mitigation=str(v.get("requiredAction") or "Apply vendor patch immediately"),
            ))
    return findings


# ---------------------------------------------------------------------------
# Dependency confusion detector (PyPI probe)
# ---------------------------------------------------------------------------

async def check_dependency_confusion(
    packages: List[str],
    internal_prefixes: List[str],
) -> List[SupplyChainFinding]:
    """Probe PyPI for internal-named packages — dependency confusion risk."""
    findings: List[SupplyChainFinding] = []
    candidates = [
        p for p in packages
        if any(p.startswith(pfx.lower()) for pfx in internal_prefixes)
    ]
    if not candidates:
        return findings

    async def _probe(pkg: str) -> Optional[SupplyChainFinding]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"https://pypi.org/pypi/{pkg}/json")
            if r.status_code == 200:
                ver = (r.json().get("info") or {}).get("version", "unknown")
                return SupplyChainFinding(
                    package=pkg,
                    attack_type="dependency_confusion",
                    severity="critical",
                    detail=(
                        f"Internal package '{pkg}' found on PyPI (v{ver}). "
                        "Pip may pull the public version instead of your private one."
                    ),
                    mitigation=(
                        "Set --index-url to your private registry, or add "
                        f"'{pkg}' to pip's allowed-hosts with hash pinning."
                    ),
                )
        except Exception:
            pass
        return None

    results = await asyncio.gather(*[_probe(p) for p in candidates], return_exceptions=True)
    for r in results:
        if isinstance(r, SupplyChainFinding):
            findings.append(r)
    return findings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_supply_chain_scan(
    repo_root: Optional[str] = None,
    internal_prefixes: Optional[List[str]] = None,
    create_tickets: bool = True,
) -> SupplyChainScanReport:
    """Run full supply chain scan.

    Parameters
    ----------
    repo_root : str, optional
        Repo root containing requirements*.txt. Defaults to CWD.
    internal_prefixes : list[str], optional
        Package prefixes treated as internal (dependency confusion check).
        Defaults to INTERNAL_PKG_PREFIXES env var or ['shopsquire'].
    create_tickets : bool
        Auto-create tickets for critical findings via TicketingAgent.
    """
    root = Path(repo_root or os.getcwd())
    prefixes = internal_prefixes or [
        p.strip()
        for p in os.getenv("INTERNAL_PKG_PREFIXES", "shopsquire").split(",")
        if p.strip()
    ]

    report = SupplyChainScanReport()
    packages = collect_packages(root)
    report.scanned_packages = packages

    if not packages:
        report.errors.append(f"No requirements.txt files found in {root}")
        return report

    log.info("supply_chain_security: scanning %d packages", len(packages))

    try:
        typo = check_typosquatting(packages)
        kev, confusion = await asyncio.gather(
            check_cisa_kev(packages),
            check_dependency_confusion(packages, prefixes),
        )
        report.findings = typo + kev + confusion
    except Exception as exc:
        report.errors.append(f"scan_error: {exc}")
        log.error("supply_chain_security: scan failed: %s", exc)

    # Emit decision trace
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(
            None, "supply_chain_scan", "agent", "SupplyChain_Security_Agent",
            "system", None,
            {
                "scanned": len(packages),
                "findings": len(report.findings),
                "critical": report.critical_count,
                "attack_types": list({f.attack_type for f in report.findings}),
            },
        )
    except Exception:
        pass

    # Auto-ticket criticals
    if create_tickets and report.critical_count > 0:
        try:
            from src.app.services.ticketing import TicketingAgent
            agent = TicketingAgent()
            for f in report.findings:
                if f.severity == "critical":
                    agent.create_ticket(
                        title=f"Supply chain: {f.attack_type} — {f.package}",
                        description=f"{f.detail}\n\nMitigation: {f.mitigation}",
                        severity="critical",
                        reason_code=f"supply_chain_{f.attack_type}",
                        evidence_snapshot={"package": f.package, "cve_id": f.cve_id},
                    )
        except Exception as exc:
            log.error("supply_chain_security: ticket creation failed: %s", exc)
            report.errors.append(f"ticket_error: {exc}")

    if report.findings:
        log.warning(
            "supply_chain_security: %d findings (%d critical) in %d packages",
            len(report.findings), report.critical_count, len(packages),
        )
    else:
        log.info("supply_chain_security: clean — no risks in %d packages", len(packages))

    return report
