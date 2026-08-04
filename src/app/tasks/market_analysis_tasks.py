"""Market analysis batch (Celery) — runs M3 detectors + PERSISTS findings for the hot path to read.

Analysis runs the real statistical models (~1.6s), so it is batch-only; the request path reads the
persisted market_finding rows. DEFAULT-OFF (MARKET_ANALYSIS_ENABLED). Errors logged + isolated.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return str(os.getenv("MARKET_ANALYSIS_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _tenant_ids() -> tuple[str, ...]:
    """Bounded authoritative worker fan-out; never depends on a request-local header."""
    from src.app.tasks.market_signal_tasks import _canonical_tenant_ids
    return _canonical_tenant_ids() or ("default",)


@celery_app.task(name="src.app.tasks.market_analysis_tasks.run_market_analysis")
def run_market_analysis() -> Dict[str, Any]:
    if not _enabled():
        return {"skipped": "disabled"}
    try:
        limit = max(1, int(float(os.getenv("MARKET_ANALYSIS_LIMIT", "5000") or 5000)))
        from src.app.models.db import db_session
        from src.app.services.market_analysis import persist_findings, run_analysis
        reports: Dict[str, Dict[str, int]] = {}
        with db_session() as db:
            for tenant_id in _tenant_ids():
                findings = run_analysis(db, limit=limit, tenant_id=tenant_id)
                # This tenant's run is its current truth; never expire another tenant's findings.
                written = persist_findings(
                    db, findings, tenant_id=tenant_id, expire_unobserved=True)
                reports[tenant_id] = {"findings": len(findings), "persisted": int(written or 0)}
            db.commit()
        out = {
            "findings": sum(row["findings"] for row in reports.values()),
            "persisted": sum(row["persisted"] for row in reports.values()),
            "tenants": reports,
        }
        logger.info("run_market_analysis %s", out)
        return out
    except Exception as exc:
        logger.warning("run_market_analysis failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}


def _pipeline_enabled() -> bool:
    return str(os.getenv("MARKET_PIPELINE_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@celery_app.task(name="src.app.tasks.market_analysis_tasks.run_market_pipeline")
def run_market_pipeline() -> Dict[str, Any]:
    """The REAL pipeline in one task: bounded tenant fan-out over ingest → analyze → persist.
    Scheduled via beat (MARKET_PIPELINE_ENABLED) and triggerable on demand by the operator."""
    if not _pipeline_enabled():
        return {"skipped": "disabled"}
    try:
        limit = max(1, int(float(os.getenv("MARKET_PIPELINE_LIMIT", "2000") or 2000)))
        from src.app.models.db import db_session
        from src.app.services.market_pipeline import run_pipeline
        reports: Dict[str, Dict[str, Any]] = {}
        with db_session() as db:
            for tenant_id in _tenant_ids():
                reports[tenant_id] = run_pipeline(db, tenant_id=tenant_id, limit=limit)
        out: Dict[str, Any] = {
            "ingested": sum(int(row.get("ingested") or 0) for row in reports.values()),
            "findings": sum(int(row.get("findings") or 0) for row in reports.values()),
            "persisted": sum(int(row.get("persisted") or 0) for row in reports.values()),
            "tenants": reports,
        }
        logger.info("run_market_pipeline %s", out)
        return out
    except Exception as exc:
        logger.warning("run_market_pipeline failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
