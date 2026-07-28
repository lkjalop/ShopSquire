from __future__ import annotations

import os
from typing import Any

from src.app.workers.celery_app import celery_app


@celery_app.task(name="src.app.tasks.connector_recovery_tasks.recover_stalled_connector_jobs")
def recover_stalled_connector_jobs() -> dict[str, Any]:
    from src.app.erp.connector_runtime import (
        recover_stalled_erp_outbound,
        recover_stalled_inventory_runs,
    )

    stale_seconds = max(
        30, int(os.getenv("CONNECTOR_STALLED_AFTER_SEC", "900") or 900)
    )
    return {
        "inventory_runs": recover_stalled_inventory_runs(
            stale_after_seconds=stale_seconds
        ),
        "outbound_jobs": recover_stalled_erp_outbound(
            stale_after_seconds=stale_seconds
        ),
    }
