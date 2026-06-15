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


# ---------------------------------------------------------------------------
# Auth token expiry cleanup — runs daily at 03:15 UTC
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="src.app.tasks.security_poll_tasks.prune_expired_auth_tokens",
    max_retries=2,
    default_retry_delay=300,
)
def prune_expired_auth_tokens(self) -> Dict[str, Any]:
    """Delete expired session_tokens and refresh_tokens rows.

    Both tables grow unboundedly without this cleanup.  Auth query latency
    degrades as the tables accumulate millions of expired rows over months.
    Safe to retry: DELETE WHERE expires_at < NOW() is idempotent.
    """
    import os
    from sqlalchemy import text as _sql

    try:
        from src.app.models.db import db_session

        cutoff = os.getenv("TOKEN_PRUNE_KEEP_DAYS", "7")
        with db_session() as db:
            r1 = db.execute(
                _sql(
                    "DELETE FROM session_tokens"
                    " WHERE expires_at IS NOT NULL"
                    f" AND expires_at < (CURRENT_TIMESTAMP - INTERVAL '{cutoff} days')"
                )
            )
            r2 = db.execute(
                _sql(
                    "DELETE FROM refresh_tokens"
                    " WHERE expires_at IS NOT NULL"
                    f" AND expires_at < (CURRENT_TIMESTAMP - INTERVAL '{cutoff} days')"
                )
            )
            try:
                db.commit()
            except Exception:
                pass
        session_pruned = getattr(r1, "rowcount", 0) or 0
        refresh_pruned = getattr(r2, "rowcount", 0) or 0
        logger.info(
            "prune_expired_auth_tokens: pruned %d session_tokens, %d refresh_tokens",
            session_pruned,
            refresh_pruned,
        )
        return {
            "ok": True,
            "session_tokens_pruned": int(session_pruned),
            "refresh_tokens_pruned": int(refresh_pruned),
        }
    except Exception as exc:
        logger.error("prune_expired_auth_tokens failed: %s", exc)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {"ok": False, "error": str(exc)}
