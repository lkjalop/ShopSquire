from __future__ import annotations

from typing import Dict
from typing import Any

import os
import httpx
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text as sql_text
from src.app.models.db import db_session
from src.app.deps import get_redis
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
from src.app.security.supply_chain_automation import correlate_local_sboms
from src.app.security.threat_intel_automation import sync_all_automated_feeds
from src.app.security.pcap_analyzer import analyze_pcap_payload
from src.app.security.pcap_analyzer import correlate_network_findings
from src.app.security.bimi_verifier import verify_bimi_provider_backed
from src.app.security.email_security import evaluate_email_security
from src.app.security.vuln_scan import run_vulnerability_scan
from src.app.security.pentest_bounds import run_pentest_simulation
from src.app.security.security_event_ingest import ingest_security_event, replay_event_policy
from src.app.security.vendor_connectors import pull_crowdstrike_and_ingest, ingest_firewall_syslog_lines
from src.app.security.model_theft import model_theft_runtime_report
from src.app.services.decision_log import log_trace_event
from src.app.models.compliance_registry import ensure_compliance_registry_table, insert_artifact
from src.app.services.ticketing import TicketingAgent
import uuid
import json


router = APIRouter(prefix="/api/v1/security", tags=["security"])


@router.get("/llm10/runtime-report")
def llm10_runtime_report(
    uid: str | None = None,
    source_ip: str | None = None,
    api_key_id: str | None = None,
    redis=Depends(get_redis),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    try:
        return model_theft_runtime_report(
            redis_client=redis,
            uid=uid,
            source_ip=source_ip,
            api_key_id=api_key_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"llm10_runtime_report_failed: {exc}")


@router.get("/email/workflow-report")
def email_workflow_report(
    days: int = 30,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER, ROLE_MERCHANT])),
) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 180))
    out: Dict[str, Any] = {
        "window_days": days,
        "totals": {
            "incidents": 0,
            "bimi_verified": 0,
            "bimi_failed": 0,
            "arc_valid": 0,
            "arc_invalid": 0,
            "oob_required": 0,
            "oob_completed": 0,
        },
        "rates": {},
    }
    try:
        start_ts = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with db_session() as db:
            rows = db.execute(
                sql_text(
                    """
                    SELECT reasons_json, evidence_json, tags_json
                    FROM email_security_incidents
                    WHERE created_at >= :start_ts
                    """
                ),
                {"start_ts": start_ts},
            ).fetchall()
            for r in rows or []:
                out["totals"]["incidents"] += 1
                indicators = []
                try:
                    reasons = json.loads(str(r[0] or "[]"))
                    evidence = json.loads(str(r[1] or "{}"))
                    tags = json.loads(str(r[2] or "[]"))
                    if isinstance(reasons, list):
                        indicators.extend(reasons)
                    if isinstance(tags, list):
                        indicators.extend(tags)
                    if isinstance(evidence, dict):
                        # Normalize common incident evidence structures into indicator tokens.
                        ev_tokens = []
                        for k, v in evidence.items():
                            if isinstance(v, bool) and v:
                                ev_tokens.append(str(k))
                            elif isinstance(v, str):
                                ev_tokens.append(v)
                        indicators.extend(ev_tokens)
                except Exception:
                    indicators = []
                types = set()
                for x in indicators:
                    if isinstance(x, dict):
                        types.add(str((x or {}).get("type") or "").strip().lower())
                    else:
                        types.add(str(x or "").strip().lower())
                if "bimi_validated" in types or "bimi_provider_verified" in types:
                    out["totals"]["bimi_verified"] += 1
                if "bimi_validation_failed" in types or "bimi_provider_verification_failed" in types:
                    out["totals"]["bimi_failed"] += 1
                if "arc_chain_valid" in types:
                    out["totals"]["arc_valid"] += 1
                if "arc_chain_invalid" in types:
                    out["totals"]["arc_invalid"] += 1
                if "oob_verification_required" in types:
                    out["totals"]["oob_required"] += 1
                if "oob_verification_completed" in types:
                    out["totals"]["oob_completed"] += 1
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"email_workflow_report_failed: {exc}")
    inc = max(1, int(out["totals"]["incidents"]))
    out["rates"] = {
        "bimi_verified_rate": round(float(out["totals"]["bimi_verified"]) / float(inc), 4),
        "arc_invalid_rate": round(float(out["totals"]["arc_invalid"]) / float(inc), 4),
        "oob_completion_rate": round(
            float(out["totals"]["oob_completed"]) / float(max(1, out["totals"]["oob_required"])),
            4,
        ),
    }
    return out


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


@router.post("/supply_chain/sbom/correlate-local")
def supply_chain_sbom_correlate_local(
    payload: Dict[str, Any] | None = None,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    p = payload if isinstance(payload, dict) else {}
    return correlate_local_sboms(tenant_id=p.get("tenant_id"))


@router.post("/threat_intel/sync/automated")
def threat_intel_sync_automated(
    payload: Dict[str, Any] | None = None,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    p = payload if isinstance(payload, dict) else {}
    return sync_all_automated_feeds(tenant_id=p.get("tenant_id"))


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


@router.post("/pcap/analyze")
def pcap_analyze(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return analyze_pcap_payload(
        pcap_b64=str(payload.get("pcap_b64") or ""),
        max_packets=int(payload.get("max_packets") or 12000),
    )


@router.post("/pcap/analyze-and-correlate")
def pcap_analyze_and_correlate(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    analyzed = analyze_pcap_payload(
        pcap_b64=str(payload.get("pcap_b64") or ""),
        max_packets=int(payload.get("max_packets") or 12000),
    )
    correlated = correlate_network_findings(
        trace_id=str(payload.get("trace_id") or ""),
        tenant_id=str(payload.get("tenant_id") or ""),
        analyzer_output=analyzed,
        source=str(payload.get("source") or "pcap_ingest"),
    )
    try:
        if correlated.get("trace_id"):
            log_trace_event(
                trace_id=str(correlated.get("trace_id")),
                event_type="network_correlated_detection",
                source_type="agent",
                source_id="NDR_PCAP_Agent",
                target_type="system",
                target_id=None,
                payload=correlated,
            )
    except Exception:
        pass
    return {"analysis": analyzed, "correlation": correlated}


@router.post("/email/bimi/verify")
def email_bimi_verify(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER, ROLE_MERCHANT])),
) -> Dict[str, Any]:
    return verify_bimi_provider_backed(payload if isinstance(payload, dict) else {})


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


@router.post("/vulnerability/scan")
def vulnerability_scan(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    result = run_vulnerability_scan(
        tenant_id=str(payload.get("tenant_id") or ""),
        targets=list(payload.get("targets") or []),
        profile=str(payload.get("profile") or "baseline"),
        provider=str(payload.get("provider") or os.getenv("VULN_SCAN_PROVIDER", "mock")),
        dry_run=bool(payload.get("dry_run", True)),
    )
    try:
        ensure_compliance_registry_table()
        insert_artifact(
            id=str(uuid.uuid4()),
            artifact_type="vulnerability_scan",
            vendor=str(result.get("provider") or "unknown"),
            scan_id=str(payload.get("trace_id") or payload.get("scan_id") or "") or None,
            status=("pass" if result.get("ok") and not result.get("reason") else "warn"),
            details=json.dumps({"request": payload, "result": result}, ensure_ascii=False),
        )
    except Exception:
        pass
    return result


@router.post("/pentest/simulate")
def pentest_simulate(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    result = run_pentest_simulation(payload)
    try:
        ensure_compliance_registry_table()
        insert_artifact(
            id=str(uuid.uuid4()),
            artifact_type="pentest",
            vendor="internal_sim",
            scan_id=str(payload.get("trace_id") or payload.get("run_id") or "") or None,
            status=("pass" if result.get("ok") else "fail"),
            details=json.dumps({"request": payload, "result": result}, ensure_ascii=False),
        )
    except Exception:
        pass
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/events/ingest")
def security_events_ingest(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    vendor = str(payload.get("vendor") or "siem")
    event_payload = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    raw_targets = payload.get("storage_targets") if isinstance(payload.get("storage_targets"), list) else None
    storage_targets = [str(t).strip().lower() for t in (raw_targets or []) if str(t).strip()]
    out = ingest_security_event(
        vendor=vendor,
        payload=event_payload if isinstance(event_payload, dict) else {},
        storage_targets=storage_targets or None,
    )
    policy = out.get("policy") if isinstance(out.get("policy"), dict) else {}
    canonical = out.get("canonical") if isinstance(out.get("canonical"), dict) else {}
    corr = out.get("correlation") if isinstance(out.get("correlation"), dict) else {}
    trace_id = str(canonical.get("trace_id") or payload.get("trace_id") or "").strip()
    if trace_id:
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="security_event_ingested",
                source_type="agent",
                source_id="Security_Ingest_Agent",
                target_type="system",
                target_id=None,
                payload={"vendor": vendor, "policy": policy, "correlation": corr, "event_id": out.get("id")},
            )
        except Exception:
            pass
    action = str(policy.get("action") or "").lower()
    ticket = None
    if action in {"escalate", "block"}:
        try:
            t = TicketingAgent().create_ticket(
                title=f"Security event {action}: {canonical.get('type') or 'unknown'}",
                description=json.dumps(
                    {
                        "vendor": vendor,
                        "event_id": out.get("id"),
                        "trace_id": trace_id,
                        "policy": policy,
                        "canonical": canonical,
                        "correlation": corr,
                    },
                    ensure_ascii=False,
                )[:4000],
                severity=("high" if action == "escalate" else "critical"),
                tenant_id=str(canonical.get("tenant_id") or "default"),
                trace_id=trace_id or None,
                reason_code="security_event_policy_escalation",
                approval_required=(action == "block"),
            )
            ticket = {"id": t.id, "status": t.status}
        except Exception:
            ticket = None
    return {"ok": True, **out, "ticket": ticket}


@router.get("/events/replay/{event_id}")
def security_events_replay(
    event_id: str,
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    out = replay_event_policy(event_id)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out)
    return out


@router.post("/events/pull/crowdstrike")
def security_events_pull_crowdstrike(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    out = pull_crowdstrike_and_ingest(
        tenant_id=str(payload.get("tenant_id") or "default"),
        trace_id=str(payload.get("trace_id") or "").strip() or None,
        limit=int(payload.get("limit") or 50),
        lookback_minutes=int(payload.get("lookback_minutes") or 60),
    )
    tid = str(payload.get("trace_id") or "").strip()
    if tid:
        try:
            log_trace_event(
                trace_id=tid,
                event_type="vendor_pull_crowdstrike",
                source_type="agent",
                source_id="CrowdStrike_Pull_Agent",
                target_type="system",
                target_id=None,
                payload={"ok": out.get("ok"), "ingested": out.get("ingested"), "reason": out.get("reason")},
            )
        except Exception:
            pass
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out)
    return out


@router.post("/events/ingest/firewall-syslog")
def security_events_ingest_firewall_syslog(
    payload: Dict[str, Any],
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    lines = payload.get("lines") if isinstance(payload.get("lines"), list) else []
    if not lines:
        raise HTTPException(status_code=400, detail="lines_required")
    out = ingest_firewall_syslog_lines(
        lines=[str(x) for x in lines],
        tenant_id=str(payload.get("tenant_id") or "default"),
        trace_id=str(payload.get("trace_id") or "").strip() or None,
    )
    tid = str(payload.get("trace_id") or "").strip()
    if tid:
        try:
            log_trace_event(
                trace_id=tid,
                event_type="vendor_ingest_firewall_syslog",
                source_type="agent",
                source_id="Firewall_Syslog_Agent",
                target_type="system",
                target_id=None,
                payload={"ok": out.get("ok"), "ingested": out.get("ingested")},
            )
        except Exception:
            pass
    return out
