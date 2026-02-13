from __future__ import annotations

from typing import Dict
from typing import Any

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.security_playbooks import get_cv_playbook_map
from src.app.security.redteam.suite import run_suite, run_mutation_campaign, get_benchmark_trends
from src.app.security.redteam.swarm import start_swarm, get_swarm
from src.app.security.supply_chain_controls import (
    ingest_sbom_and_correlate,
    check_oauth_scope_anomaly,
    verify_partner_artifact_signature,
    verify_slsa_attestation,
)
from src.app.security.email_security import evaluate_email_security


router = APIRouter(prefix="/api/v1/security", tags=["security"])


@router.get("/health")
async def security_integrations_health() -> Dict:
    """Validate presence of SIEM/EDR connector configuration and basic connectivity.

    This does not send events; it performs GET/HEAD requests where possible.
    """
    status: Dict[str, Dict] = {}

    # CrowdStrike
    cs_client_id = os.getenv("CROWDSTRIKE_CLIENT_ID")
    cs_client_secret = os.getenv("CROWDSTRIKE_CLIENT_SECRET")
    cs_api = os.getenv("CROWDSTRIKE_API_URL", "https://api.crowdstrike.com")
    cs_ok = bool(cs_client_id and cs_client_secret)
    cs_conn = False
    if cs_ok:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{cs_api}/oauth2/token")
                cs_conn = (r.status_code in (400, 405, 404, 200))
        except Exception:
            cs_conn = False
    status["crowdstrike"] = {"configured": cs_ok, "basic_connectivity": cs_conn}

    # Splunk HEC
    hec_url = os.getenv("SPLUNK_HEC_URL")
    hec_token = os.getenv("SPLUNK_HEC_TOKEN")
    hec_ok = bool(hec_url and hec_token)
    hec_conn = False
    if hec_ok:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Expect SPLUNK_HEC_URL to point to the HEC collector base, e.g. https://host:8088/services/collector
                # Health endpoint is the same base with "/health" suffix.
                r = await client.get(f"{hec_url.rstrip('/')}/health")
                hec_conn = (r.status_code in (200, 404))
        except Exception:
            hec_conn = False
    status["splunk_hec"] = {"configured": hec_ok, "basic_connectivity": hec_conn}

    # Elastic Security
    elastic_url = os.getenv("ELASTIC_SECURITY_EVENTS_URL")
    elastic_ok = bool(elastic_url)
    elastic_conn = False
    if elastic_ok:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(elastic_url)
                elastic_conn = (r.status_code in (200, 201, 202, 401, 403, 404, 405))
        except Exception:
            elastic_conn = False
    status["elastic"] = {"configured": elastic_ok, "basic_connectivity": elastic_conn}

    # Sentinel Logic App / ingestion webhook
    sentinel_url = os.getenv("SENTINEL_INGEST_URL")
    sentinel_ok = bool(sentinel_url)
    sentinel_conn = False
    if sentinel_ok:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(sentinel_url)
                sentinel_conn = (r.status_code in (200, 201, 202, 401, 403, 404, 405))
        except Exception:
            sentinel_conn = False
    status["sentinel"] = {"configured": sentinel_ok, "basic_connectivity": sentinel_conn}

    # CSPM handoff endpoint
    cspm_url = os.getenv("CSPM_INGEST_URL")
    cspm_ok = bool(cspm_url)
    cspm_conn = False
    if cspm_ok:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(cspm_url)
                cspm_conn = (r.status_code in (200, 201, 202, 401, 403, 404, 405))
        except Exception:
            cspm_conn = False
    status["cspm"] = {"configured": cspm_ok, "basic_connectivity": cspm_conn}

    return {"status": status}


@router.get("/demo/events")
async def security_demo_events(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Admin-only demo endpoint returning recent security events for popup.

    Shoppers do not have access; protected by role guard.
    """
    events = [
        {
            "id": "ev-aml-t0043",
            "time": "2026-01-24T10:15:00Z",
            "severity": "warn",
            "technique": "AML.T0043 Prompt Injection",
            "user": "demo-user",
            "action": "neutralized",
            "summary": "Blocked malicious prompt attempting to bypass guardrails",
        },
        {
            "id": "ev-aml-t0020",
            "time": "2026-01-24T10:29:00Z",
            "severity": "high",
            "technique": "AML.T0020 Supply Chain",
            "user": "system",
            "action": "escalated",
            "summary": "Vendor manifest integrity check failed for connector XYZ",
        },
        {
            "id": "ev-iam-anom-01",
            "time": "2026-01-24T10:34:00Z",
            "severity": "info",
            "technique": "IAM Anomaly",
            "user": "ops-admin",
            "action": "allowed",
            "summary": "Admin login from trusted IP range",
        },
    ]
    return {"events": events}


@router.get("/playbooks/cv")
async def get_cv_playbooks(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Return CV playbook mapping for audit and UI selection."""
    return get_cv_playbook_map()


@router.post("/redteam/run")
def run_redteam(
    mutate: bool = False,
    max_mutations_per_case: int = 5,
    persist: bool = True,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    """Run static red-team suite or mutation campaign and return summary."""
    if mutate:
        return run_mutation_campaign(max_mutations_per_case=max_mutations_per_case, persist=persist)
    results = run_suite()
    total = len(results)
    detected = 0
    for r in results:
        if str(r.get("severity") or "").lower() in ("high", "critical", "error"):
            detected += 1
    return {
        "mode": "static",
        "total_cases": total,
        "detected_cases": detected,
        "detection_rate": round(float(detected) / float(max(1, total)), 4),
        "results": results,
    }


@router.get("/redteam/benchmarks")
def redteam_benchmarks(
    days: int = 30,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return get_benchmark_trends(days=days)


@router.post("/redteam/swarm/start")
def redteam_swarm_start(
    rounds: int = 3,
    max_mutations_per_case: int = 6,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return start_swarm(rounds=rounds, max_mutations_per_case=max_mutations_per_case)


@router.get("/redteam/swarm/{job_id}")
def redteam_swarm_status(
    job_id: str,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return get_swarm(job_id)


@router.post("/supply_chain/sbom/ingest")
def supply_chain_sbom_ingest(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tenant_id = payload.get("tenant_id")
    sbom = payload.get("sbom") if isinstance(payload.get("sbom"), dict) else payload
    return ingest_sbom_and_correlate(sbom, tenant_id=tenant_id)


@router.post("/supply_chain/oauth/scope/check")
def supply_chain_oauth_scope_check(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return check_oauth_scope_anomaly(
        partner=str(payload.get("partner") or ""),
        granted_scopes=list(payload.get("granted_scopes") or []),
        baseline_scopes=list(payload.get("baseline_scopes") or []),
        tenant_id=payload.get("tenant_id"),
    )


@router.post("/supply_chain/artifact/verify")
def supply_chain_artifact_verify(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return verify_partner_artifact_signature(
        artifact_b64=str(payload.get("artifact_b64") or ""),
        signature=str(payload.get("signature") or ""),
        signer=(payload.get("signer") or None),
        algorithm=str(payload.get("algorithm") or "sha256"),
    )


@router.post("/supply_chain/slsa/verify")
def supply_chain_slsa_verify(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    attestation = payload.get("attestation") if isinstance(payload.get("attestation"), dict) else payload
    sbom = payload.get("sbom") if isinstance(payload.get("sbom"), dict) else None
    return verify_slsa_attestation(attestation, sbom=sbom)


@router.get("/sbom/readiness")
def sbom_readiness(
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    kev_path = os.getenv("KEV_CATALOG_PATH", "config/security/taxonomy/kev_catalog.json")
    signer_cfg = os.getenv("TRUSTED_PARTNER_SIGNERS", "")
    return {
        "sbom_ingest_endpoint": "/api/v1/security/supply_chain/sbom/ingest",
        "kev_catalog_path": kev_path,
        "kev_catalog_present": bool(os.path.exists(kev_path)),
        "trusted_signers_configured": bool(str(signer_cfg).strip()),
        "artifact_verify_endpoint": "/api/v1/security/supply_chain/artifact/verify",
        "slsa_verify_endpoint": "/api/v1/security/supply_chain/slsa/verify",
        "production_ready": bool(os.path.exists(kev_path) and str(signer_cfg).strip()),
    }


@router.post("/selftest/vulnerability")
def selftest_vulnerability(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tenant_id = str(payload.get("tenant_id") or "selftest-tenant")
    tests = []
    # LOLBins + delivery combo test
    msg = {
        "message_id": "<selftest-lolbin@shopsquire.local>",
        "from_addr": "ops@micros0ft.com",
        "reply_to": "ops@evil-payments.example",
        "subject": "Run certutil and bitsadmin now",
        "body": "powershell -enc abc123 ; download from https://evil.example/payload",
        "attachments": [{"name": "update.js", "sha256": "a" * 64}],
        "spf_result": "fail",
        "dkim_result": "fail",
        "dmarc_result": "fail",
        "dmarc_policy": "reject",
        "external_sender": True,
    }
    verdict = evaluate_email_security(msg, tenant_id=tenant_id)
    tests.append(
        {
            "name": "email_lolbin_delivery_combo",
            "passed": bool("lolbin_delivery_combo" in [str((i or {}).get("type") or "") for i in (verdict.get("indicators") or [])]),
            "route": verdict.get("route"),
            "severity": verdict.get("severity"),
        }
    )
    return {
        "tenant_id": tenant_id,
        "tests": tests,
        "pass_rate": round(float(sum(1 for t in tests if t.get("passed"))) / float(max(1, len(tests))), 4),
    }
