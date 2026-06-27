"""Market-intelligence pipeline (agnostic CORE) — the REAL ingestion → analysis → findings path.

One call turns live source rows into persisted findings, the same path the synthetic replay exercises
but on REAL data (default tenant), tenant-scoped so it never picks up replay-demo signals:
  1. backfill_from_db — normalize recent orders / conversion / search / returns into market_signal
     (idempotent via dedup);
  2. run_analysis — the M3 detectors over THIS tenant's signals (real statistical models ~1.6s, so this
     is batch / operator-triggered, never the request path);
  3. persist_findings — supersede the prior active findings (expire the ones no longer observed).

Vertical-blind; best-effort; never raises into the caller. Returns the run counts.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

DEFAULT_TENANT = "default"


def run_pipeline(db, *, tenant_id: str = DEFAULT_TENANT, limit: int = 2000, min_trust: float = 0.0,
                 anomaly_fn: Optional[Callable] = None, forecast_fn: Optional[Callable] = None,
                 expire_unobserved: bool = True, commit: bool = True) -> Dict[str, Any]:
    """Ingest real source rows → analyze this tenant's signals → persist findings. Returns
    {ingested, ingested_by_source, findings, persisted}. ``anomaly_fn`` is injectable (tests pass a
    deterministic one to skip the heavy models). Best-effort; never raises."""
    if db is None:
        return {"ingested": 0, "ingested_by_source": {}, "findings": 0, "persisted": 0}
    try:
        from src.app.services.market_analysis import persist_findings, run_analysis
        from src.app.services.market_signal_adapters import backfill_from_db
        ingested = backfill_from_db(db, limit=limit, min_trust=min_trust, commit=False) or {}
        findings = run_analysis(db, limit=limit, anomaly_fn=anomaly_fn, forecast_fn=forecast_fn,
                                tenant_id=tenant_id)
        persisted = persist_findings(db, findings, tenant_id=tenant_id, expire_unobserved=expire_unobserved)
        result = {"ingested": int(sum(int(v or 0) for v in ingested.values())),
                  "ingested_by_source": ingested, "findings": len(findings), "persisted": int(persisted or 0)}
        if commit:
            try:
                db.commit()
            except Exception as exc:  # keep the counts; a commit failure is logged, not swallowed silently
                import logging
                logging.getLogger(__name__).warning("market_pipeline commit failed: %s", exc)
        return result
    except Exception as exc:
        # Step 10: a pipeline failure must reach a governed disposition, not vanish. enqueue_exception is
        # non-raising (best-effort), so this stays a safe fallback that still returns the zero-result shape.
        from src.app.services.exception_resolver import enqueue_exception
        enqueue_exception(domain="market", terminal_outcome="pipeline_error", reason=str(exc)[:200],
                          tenant_id=tenant_id)
        return {"ingested": 0, "ingested_by_source": {}, "findings": 0, "persisted": 0}


def state(db, *, tenant_id: str = DEFAULT_TENANT, limit: int = 50) -> Dict[str, Any]:
    """Operator view of the REAL findings (mirrors market_replay.state, tenant=default). Best-effort."""
    if db is None:
        return {"signals": 0, "active_findings": 0, "findings": [], "label": "LIVE"}
    try:
        from sqlalchemy import text
        from src.app.services.market_analysis import load_recent_findings
        try:
            sig_n = db.execute(text("SELECT COUNT(*) FROM market_signal WHERE COALESCE(tenant_id,'default')=:t"),
                               {"t": tenant_id}).scalar() or 0
        except Exception:
            sig_n = 0
        findings = load_recent_findings(db, limit=limit, tenant_id=tenant_id)
        return {
            "signals": int(sig_n),
            "active_findings": len(findings),
            "findings": [{"type": f.finding_type, "severity": f.severity, "summary": f.summary,
                          "entity_ref": f.entity_ref} for f in findings],
            "label": "LIVE",
        }
    except Exception:
        return {"signals": 0, "active_findings": 0, "findings": [], "label": "LIVE"}
