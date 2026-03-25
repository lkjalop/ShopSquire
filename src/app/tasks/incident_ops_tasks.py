from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from src.app.workers.celery_app import celery_app

_log = logging.getLogger("shopsquire.tasks.incident_ops")


def _load_scheduled_scan_configs() -> list[dict]:
    configs: list[dict] = []
    try:
        from src.app.rules.tenant_config_store import TenantConfigStore

        store = TenantConfigStore(cache_ttl=30)
        global_cfg = store.get_override("vuln_scan_schedule", tenant_id=None) or {}
        tenants = set(str(global_cfg.get("tenant_ids") or "").split(",")) if global_cfg.get("tenant_ids") else set()
        explicit = [str(t).strip() for t in os.getenv("VULN_SCAN_SCHEDULED_TENANTS", "").split(",") if str(t).strip()]
        tenants.update(explicit)
        for tenant_id in sorted(t for t in tenants if t and t != "global"):
            cfg = store.get_override("vuln_scan_schedule", tenant_id=tenant_id) or {}
            if cfg.get("enabled", True):
                configs.append(
                    {
                        "tenant_id": tenant_id,
                        "profile": str(cfg.get("profile") or "baseline"),
                        "target_url": str(cfg.get("target_url") or "").strip(),
                        "image_ref": str(cfg.get("image_ref") or "").strip(),
                        "code_path": str(cfg.get("code_path") or "").strip(),
                    }
                )
    except Exception:
        pass

    targets_raw = os.getenv("VULN_SCAN_SCHEDULED_TARGETS", "").strip()
    if targets_raw:
        targets = [t.strip() for t in targets_raw.split(",") if t.strip()]
        tenant_id = os.getenv("VULN_SCAN_SCHEDULED_TENANT_ID", "default").strip() or "default"
        profile = os.getenv("VULN_SCAN_SCHEDULED_PROFILE", "baseline").strip() or "baseline"
        for target in targets:
            item = {
                "tenant_id": tenant_id,
                "profile": profile,
                "target_url": target if target.startswith("http") else "",
                "image_ref": "" if target.startswith("http") else target,
                "code_path": "",
            }
            if item not in configs:
                configs.append(item)
    return [cfg for cfg in configs if cfg.get("target_url") or cfg.get("image_ref") or cfg.get("code_path")]


def _persist_scan_scorecard(*, tenant_id: str, profile: str, target: str, summary: dict) -> None:
    from src.app.models.db import db_session
    from sqlalchemy import text

    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO security_scan_scorecards
                    (id, tenant_id, profile, target, risk_score, total_findings, critical_count, high_count, summary_json, created_at)
                    VALUES (:id, :tenant_id, :profile, :target, :risk_score, :total_findings, :critical_count, :high_count, :summary_json, :created_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": tenant_id,
                    "profile": profile,
                    "target": target,
                    "risk_score": float(summary.get("risk_score") or 0.0),
                    "total_findings": int(summary.get("total_findings") or 0),
                    "critical_count": int(summary.get("critical") or 0),
                    "high_count": int(summary.get("high") or 0),
                    "summary_json": json.dumps(summary or {}, ensure_ascii=False),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            db.commit()
    except Exception as exc:
        _log.warning("scheduled vuln scorecard persist failed: %s", exc)


@celery_app.task(name="src.app.tasks.incident_ops_tasks.check_incident_sla_breaches")
def check_incident_sla_breaches() -> dict:
    """Periodic SLA breach scan for escalation incidents."""
    try:
        from src.app.services.incident_sla_scheduler import run_cycle

        return run_cycle() or {"checked": 0, "breached": 0}
    except Exception as exc:
        return {"checked": 0, "breached": 0, "error": str(exc)}


@celery_app.task(name="src.app.tasks.incident_ops_tasks.scheduled_vuln_scan_daily")
def scheduled_vuln_scan_daily() -> dict:
    """Daily scheduled vulnerability scan on configured targets.

    Targets are configured via VULN_SCAN_SCHEDULED_TARGETS env var (comma-separated hosts).
    Results are auto-escalated via create_incident_record for critical/high findings.
    Requires VULN_SCAN_ENABLED=1 and VULN_SCAN_SCHEDULED_TARGETS to be set.
    """
    enabled = os.getenv("VULN_SCAN_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")
    if not enabled:
        return {"status": "disabled"}

    configs = _load_scheduled_scan_configs()
    if not configs:
        return {"status": "skipped", "reason": "no scheduled tenant/target config"}

    try:
        import asyncio

        from src.app.routers.vuln_scan import _auto_escalate_critical
        from src.app.services.vuln_scanner import VulnScanService

        results: list[dict] = []
        svc = VulnScanService()
        for cfg in configs:
            tenant_id = str(cfg.get("tenant_id") or "default")
            profile = str(cfg.get("profile") or "baseline")
            target_url = str(cfg.get("target_url") or "")
            image_ref = str(cfg.get("image_ref") or "")
            code_path = str(cfg.get("code_path") or "")
            report = asyncio.run(svc.scan_all(target_url=target_url, image_ref=image_ref, code_path=code_path))
            if report.critical_count > 0:
                asyncio.run(_auto_escalate_critical(report))
            summary = report.to_api_dict()
            summary["tenant_id"] = tenant_id
            summary["profile"] = profile
            summary["target"] = report.target
            _persist_scan_scorecard(tenant_id=tenant_id, profile=profile, target=report.target, summary=summary)
            results.append(
                {
                    "tenant_id": tenant_id,
                    "profile": profile,
                    "target": report.target,
                    "finding_count": summary.get("total_findings", 0),
                    "critical": summary.get("critical", 0),
                    "high": summary.get("high", 0),
                    "risk_score": summary.get("risk_score", 0.0),
                }
            )
        total_findings = sum(int(item.get("finding_count") or 0) for item in results)
        incidents_created = sum(int(item.get("critical") or 0) for item in results)
        summary = {"status": "ok", "scan_count": len(results), "finding_count": total_findings, "incidents_auto_created": incidents_created, "results": results}
        _log.info("Scheduled vuln scans complete: %d scans, %d findings", len(results), total_findings)
        return summary
    except Exception as exc:
        _log.error("Scheduled vuln scan failed: %s", exc)
        return {"status": "failed", "error": str(exc)[:300]}


@celery_app.task(name="src.app.tasks.incident_ops_tasks.trace_broker_recovery")
def trace_broker_recovery() -> dict:
    """Best-effort decision trace broker replay/recovery for enterprise ops."""
    try:
        import asyncio
        from src.app.services.trace_broker import recover_pending, replay_recent

        async def _run() -> dict:
            recovered = await recover_pending(max_messages=200)
            replayed = await replay_recent(count=200)
            return {"recovered": recovered, "replayed": replayed}

        return asyncio.run(_run())
    except Exception as exc:
        return {"error": str(exc)}
