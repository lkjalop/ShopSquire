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


@celery_app.task(name="src.app.tasks.market_analysis_tasks.run_market_analysis")
def run_market_analysis() -> Dict[str, Any]:
    if not _enabled():
        return {"skipped": "disabled"}
    try:
        limit = max(1, int(float(os.getenv("MARKET_ANALYSIS_LIMIT", "5000") or 5000)))
        from src.app.models.db import db_session
        from src.app.services.market_analysis import persist_findings, run_analysis
        with db_session() as db:
            findings = run_analysis(db, limit=limit)
            # expire_unobserved: this run is the current truth — retire active findings it no longer sees
            written = persist_findings(db, findings, expire_unobserved=True)
            db.commit()
        logger.info("run_market_analysis findings=%d persisted=%d", len(findings), written)
        return {"findings": len(findings), "persisted": written}
    except Exception as exc:
        logger.warning("run_market_analysis failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}


def _pipeline_enabled() -> bool:
    return str(os.getenv("MARKET_PIPELINE_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


@celery_app.task(name="src.app.tasks.market_analysis_tasks.run_market_pipeline")
def run_market_pipeline() -> Dict[str, Any]:
    """The REAL pipeline in one task: backfill real sources → analyze (default tenant) → persist.
    Scheduled via beat (MARKET_PIPELINE_ENABLED) and triggerable on demand by the operator."""
    if not _pipeline_enabled():
        return {"skipped": "disabled"}
    try:
        limit = max(1, int(float(os.getenv("MARKET_PIPELINE_LIMIT", "2000") or 2000)))
        from src.app.models.db import db_session
        from src.app.services.market_pipeline import run_pipeline
        with db_session() as db:
            out = run_pipeline(db, tenant_id="default", limit=limit)
        logger.info("run_market_pipeline %s", out)
        return out
    except Exception as exc:
        logger.warning("run_market_pipeline failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
