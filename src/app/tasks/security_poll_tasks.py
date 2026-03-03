from __future__ import annotations

from typing import Any, Dict

from src.app.workers.celery_app import celery_app
from src.app.security.vendor_connectors import pull_crowdstrike_and_ingest


@celery_app.task(bind=True, name="src.app.tasks.security_poll_tasks.poll_crowdstrike")
def poll_crowdstrike(self, tenant_id: str = "default", limit: int = 100, lookback_minutes: int = 30) -> Dict[str, Any]:
    """Scheduled CrowdStrike polling task for continuous ingestion."""
    return pull_crowdstrike_and_ingest(
        tenant_id=str(tenant_id or "default"),
        limit=max(1, min(int(limit or 100), 500)),
        lookback_minutes=max(1, min(int(lookback_minutes or 30), 24 * 60)),
    )
