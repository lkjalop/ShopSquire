from __future__ import annotations

import logging
from typing import Any, Dict

from src.app.workers.celery_app import celery_app
from src.app.security.vendor_connectors import pull_crowdstrike_and_ingest

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="src.app.tasks.security_poll_tasks.poll_crowdstrike")
def poll_crowdstrike(self, tenant_id: str = "default", limit: int = 100, lookback_minutes: int = 30) -> Dict[str, Any]:
    """Scheduled CrowdStrike polling task for continuous ingestion."""
    return pull_crowdstrike_and_ingest(
        tenant_id=str(tenant_id or "default"),
        limit=max(1, min(int(limit or 100), 500)),
        lookback_minutes=max(1, min(int(lookback_minutes or 30), 24 * 60)),
    )


# ---------------------------------------------------------------------------
# IT-DET-03 — Config file integrity check (every 5 minutes)
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="src.app.tasks.security_poll_tasks.check_config_integrity")
def check_config_integrity(self) -> Dict[str, Any]:
    """IT-DET-03: Re-hash monitored security config files and compare against baseline.

    Any mismatch means a file was changed outside the normal PR + review process.
    Violations are emitted as critical InsiderThreatSignals and Prometheus metrics.
    """
    try:
        from src.app.security.config_integrity import check_integrity
        violations = check_integrity()
        return {
            "violations": [v.to_dict() for v in violations],
            "violation_count": len(violations),
            "ok": len(violations) == 0,
        }
    except Exception as exc:
        logger.error("check_config_integrity task error: %s", exc)
        return {"violations": [], "violation_count": 0, "ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# IT-DET-05 — Prompt hash verification (every 5 minutes)
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="src.app.tasks.security_poll_tasks.verify_prompt_hashes")
def verify_prompt_hashes(self) -> Dict[str, Any]:
    """IT-DET-05: Re-verify all registered prompt hashes against the persisted hash file.

    A mismatch means a system prompt was changed at runtime without going through
    the approved PR + AI governance sign-off process.
    """
    try:
        from src.app.security.prompt_registry import verify_all
        violations = verify_all()
        return {
            "violations": violations,
            "violation_count": len(violations),
            "ok": len(violations) == 0,
        }
    except Exception as exc:
        logger.error("verify_prompt_hashes task error: %s", exc)
        return {"violations": [], "violation_count": 0, "ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# IT-DET-03b — Audit chain integrity verification (every 5 minutes)
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="src.app.tasks.security_poll_tasks.verify_audit_chain")
def verify_audit_chain(self) -> Dict[str, Any]:
    """IT-DET-03b: Walk the decision audit hash chain and verify integrity.

    Detects row-level tampering (UPDATE) or deletion (DELETE) that breaks the chain.
    """
    try:
        from src.app.models.db import db_session
        from src.app.security.insider_threat_detector import detect_audit_chain_tamper
        with db_session() as db:
            signal = detect_audit_chain_tamper(db)
        return {
            "tampered": signal is not None,
            "signal": signal.to_dict() if signal else None,
        }
    except Exception as exc:
        logger.error("verify_audit_chain task error: %s", exc)
        return {"tampered": False, "signal": None, "error": str(exc)}
