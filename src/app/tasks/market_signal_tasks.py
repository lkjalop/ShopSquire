"""Market signal backfill (Celery) — the batch wiring for Module 1 producers.

Periodically normalizes recent orders / conversions / search events into the market_signal stream
(idempotent via dedup, so re-runs are safe). DEFAULT-OFF (MARKET_SIGNAL_BACKFILL_ENABLED) — pure
ingestion (no behaviour change), but gated to avoid surprise background load until turned on. Errors
are logged and isolated; never crash the worker.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, Tuple

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return str(os.getenv("MARKET_SIGNAL_BACKFILL_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")


def _canonical_tenant_ids(explicit_tenant_id: str | None = None) -> Tuple[str, ...]:
    """Resolve a bounded tenant fan-out without request-local fallbacks."""
    explicit = str(explicit_tenant_id or "").strip()
    if explicit:
        return (explicit,)
    configured: Iterable[str] = os.getenv("MARKET_CANONICAL_TENANTS", "").split(",")
    tenants = tuple(dict.fromkeys(value.strip() for value in configured if value.strip()))
    if tenants:
        return tenants[:100]
    from src.app.platform.tenant_registry import registered_tenant_ids
    return registered_tenant_ids()[:100]


@celery_app.task(name="src.app.tasks.market_signal_tasks.market_signal_backfill")
def market_signal_backfill(tenant_id: str | None = None) -> Dict[str, Any]:
    canonical_enabled = str(os.getenv("MARKET_CANONICAL_FACTS_ENABLED", "0")).strip().lower() in (
        "1", "true", "yes", "on")
    if not _enabled() and not canonical_enabled:
        return {"skipped": "disabled"}
    try:
        limit = max(1, int(float(os.getenv("MARKET_SIGNAL_BACKFILL_LIMIT", "1000") or 1000)))
        min_trust = max(0.0, min(1.0, float(os.getenv("MARKET_SIGNAL_MIN_TRUST", "0") or 0)))
        max_age = os.getenv("MARKET_SIGNAL_MAX_AGE_SECONDS", "").strip()  # blank → no freshness gate
        max_age_seconds = float(max_age) if max_age else None
        now_iso = None
        if max_age_seconds is not None:
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        from src.app.models.db import db_session
        from src.app.services.market_signal_adapters import backfill_from_db
        with db_session() as db:
            tenants = _canonical_tenant_ids(tenant_id)
            if not tenants:
                tenants = ("default",)
            legacy_reports = (
                {
                    tid: backfill_from_db(
                        db,
                        limit=limit,
                        min_trust=min_trust,
                        max_age_seconds=max_age_seconds,
                        now_iso=now_iso,
                        tenant_id=tid,
                    )
                    for tid in tenants
                }
                if _enabled() else {}
            )
            # Keep the historic single-tenant field shape for existing operators while exposing
            # the authoritative fan-out explicitly.
            counts = (
                next(iter(legacy_reports.values()))
                if len(legacy_reports) == 1
                else {
                    source: sum(int(report.get(source) or 0) for report in legacy_reports.values())
                    for source in {
                        name for report in legacy_reports.values() for name in report
                    }
                }
            )
            canonical: Dict[str, Any] = {}
            if canonical_enabled:
                from src.app.services.canonical_fact_adapters import backfill_canonical_facts
                if not tenants:
                    canonical = {"skipped": "no_tenants_configured", "tenants": {}}
                    logger.error(
                        "canonical market backfill skipped: set MARKET_CANONICAL_TENANTS "
                        "or configure STORE_TENANT_REGISTRY"
                    )
                else:
                    reports = {
                        tid: backfill_canonical_facts(db, tenant_id=tid, limit=limit, commit=False)
                        for tid in tenants
                    }
                    db.commit()
                    canonical = {
                        "tenants": reports,
                        "written": sum(int(report.get("written") or 0) for report in reports.values()),
                        "quarantined": sum(
                            int(report.get("quarantined") or 0) for report in reports.values()
                        ),
                    }
        logger.info("market_signal_backfill counts=%s (min_trust=%s max_age=%s)", counts, min_trust, max_age_seconds)
        return {
            "legacy_signals": counts,
            "legacy_signals_by_tenant": legacy_reports,
            "canonical_facts": canonical,
        }
    except Exception as exc:
        logger.warning("market_signal_backfill failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
