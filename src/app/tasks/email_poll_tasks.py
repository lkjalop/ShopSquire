from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

from src.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="src.app.tasks.email_poll_tasks.poll_dmarc_filesystem",
    max_retries=2,
    default_retry_delay=60,
)
def poll_dmarc_filesystem(self) -> Dict[str, Any]:
    """Celery wrapper for the DMARC filesystem poll loop.

    Replaces the asyncio startup task in dmarc_poll.py.  Reads the same env
    vars (DMARC_POLL_DIR, DMARC_POLL_TENANT_ID) so deployment changes are
    config-only.  Keeps a per-worker seen-set in Redis so restarts don't
    re-process already-ingested reports.
    """
    from src.app.security.email_security import process_dmarc_report

    dmarc_dir = Path(os.getenv("DMARC_POLL_DIR", "tmp/dmarc") or "tmp/dmarc")
    tenant_id = os.getenv("DMARC_POLL_TENANT_ID") or None

    if not dmarc_dir.exists():
        try:
            dmarc_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return {"ok": True, "processed": 0, "skipped": 0, "reason": "dir_not_found"}

    # Track seen files in Redis so we survive worker restarts without re-processing.
    seen_key = f"dmarc_poll:seen:{tenant_id or 'default'}"
    seen: set[str] = set()
    try:
        from src.app.deps import get_redis
        r = get_redis()
        seen = set(r.smembers(seen_key) or [])
        # Normalise bytes → str
        seen = {v.decode() if isinstance(v, bytes) else str(v) for v in seen}
    except Exception:
        pass  # fallback: process everything (idempotent at DB level)

    processed = 0
    errors = 0
    new_seen: list[str] = []

    for pattern in ("*.xml", "*.zip"):
        for p in sorted(dmarc_dir.glob(pattern)):
            if p.name in seen:
                continue
            try:
                data = p.read_bytes()
                process_dmarc_report(data, tenant_id=tenant_id)
                new_seen.append(p.name)
                processed += 1
            except Exception as exc:
                logger.warning("DMARC poll: failed to process %s — %s", p.name, exc)
                errors += 1

    if new_seen:
        try:
            r.sadd(seen_key, *new_seen)
            r.expire(seen_key, 7 * 24 * 3600)  # TTL: 7 days
        except Exception:
            pass

    return {
        "ok": True,
        "processed": processed,
        "errors": errors,
        "tenant_id": tenant_id,
        "dir": str(dmarc_dir),
    }


@celery_app.task(
    bind=True,
    name="src.app.tasks.email_poll_tasks.poll_email_connector",
    max_retries=2,
    default_retry_delay=60,
)
def poll_email_connector(self) -> Dict[str, Any]:
    """Poll configured email inbox connectors through durable governed ingress.

    Connectors are selected via EMAIL_CONNECTOR_PROVIDER env var:
      - "gmail"   → uses ingest_gmail.py
      - "m365"    → uses ingest_m365.py (when available)
      - unset     → no-op (returns ok:True, processed:0)

    Each processed message ID is stored in Redis to prevent duplicate analysis.
    """
    provider = str(os.getenv("EMAIL_CONNECTOR_PROVIDER", "") or "").strip().lower()
    if not provider:
        return {"ok": True, "processed": 0, "provider": "none", "reason": "EMAIL_CONNECTOR_PROVIDER not set"}

    tenant_id = os.getenv("EMAIL_CONNECTOR_TENANT_ID") or None
    subscription_id = str(os.getenv("EMAIL_CONNECTOR_SUBSCRIPTION_ID") or "").strip()
    from src.app.services.connector_email_ingress import (
        identity_for_worker_item,
        persist_connector_email,
    )
    try:
        identity = identity_for_worker_item(
            provider,
            {"subscription_id": subscription_id, "tenant_id": tenant_id},
        )
    except Exception as exc:
        return {
            "ok": False,
            "processed": 0,
            "provider": provider,
            "error": f"connector_identity:{type(exc).__name__}",
        }
    batch_size = max(1, min(int(os.getenv("EMAIL_CONNECTOR_BATCH_SIZE", "20") or 20), 100))
    seen_key = f"email_connector:seen:{provider}:{identity.tenant_id}"

    seen: set[str] = set()
    r = None
    try:
        from src.app.deps import get_redis
        r = get_redis()
        raw_seen = r.smembers(seen_key) or set()
        seen = {v.decode() if isinstance(v, bytes) else str(v) for v in raw_seen}
    except Exception:
        pass

    messages: list[dict] = []
    try:
        if provider == "gmail":
            from src.app.jobs.ingest_gmail import fetch_recent_emails
            messages = fetch_recent_emails(batch_size=batch_size) or []
        elif provider == "m365":
            from src.app.jobs.ingest_m365 import fetch_recent_emails  # type: ignore[no-redef]
            messages = fetch_recent_emails(batch_size=batch_size) or []
        else:
            return {"ok": True, "processed": 0, "provider": provider, "reason": "unsupported_provider"}
    except Exception as exc:
        logger.warning("email_connector poll: fetch failed for provider=%s — %s", provider, exc)
        return {"ok": False, "processed": 0, "provider": provider, "error": str(exc)}

    processed = 0
    errors = 0
    new_seen: list[str] = []

    for msg in messages:
        msg_id = str(msg.get("message_id") or msg.get("id") or "")
        if msg_id and msg_id in seen:
            continue
        try:
            result = persist_connector_email(identity, msg)
            risk = str(result.get("risk_label") or "").lower()
            if risk in ("critical", "high"):
                logger.warning(
                    "email_connector: %s risk email detected — message_id=%s sender=%s",
                    risk,
                    msg_id,
                    msg.get("from", ""),
                )
            if msg_id:
                new_seen.append(msg_id)
            processed += 1
        except Exception as exc:
            logger.warning("email_connector poll: evaluate failed for msg %s — %s", msg_id, exc)
            errors += 1

    if new_seen and r is not None:
        try:
            r.sadd(seen_key, *new_seen)
            r.expire(seen_key, 7 * 24 * 3600)
        except Exception:
            pass

    return {
        "ok": True,
        "processed": processed,
        "errors": errors,
        "provider": provider,
        "tenant_id": identity.tenant_id,
        "subscription_id": identity.subscription_id,
    }
