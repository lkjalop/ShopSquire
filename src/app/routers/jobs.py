from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException, Depends

from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get_job(job_id: str):
    try:
        from src.app.workers.rq_queue import get_job_status
        status = get_job_status(job_id)
        if not status or status.get("status") == "unknown":
            # return 404 to indicate job not tracked or redis disabled
            raise HTTPException(status_code=404, detail={"id": job_id, "status": "unknown"})
        return status
    except HTTPException:
        raise
    except Exception:
        # tolerate missing Redis and return minimal payload
        return {"id": job_id, "status": "unknown"}


@router.get("/health/queues")
def queue_health(role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Queue depth/age snapshot with autoscale hints."""
    try:
        from src.app.workers.rq_queue import get_queue_stats
        from src.app.observability.metrics import record_worker_queue_depth, record_worker_queue_oldest_age

        stats = get_queue_stats()
        depth_thr = int(os.getenv("QUEUE_SCALE_UP_DEPTH", "100") or 100)
        age_thr = float(os.getenv("QUEUE_SCALE_UP_AGE_SECONDS", "30") or 30.0)
        hints = {}
        for qname, q in (stats.get("queues") or {}).items():
            depth = int((q or {}).get("depth") or 0)
            age = float((q or {}).get("oldest_age_seconds") or 0.0)
            # Emit gauges so /metrics reflects the latest snapshot even when
            # queue implementation is mocked or Redis is unavailable.
            try:
                record_worker_queue_depth(qname, depth)
                record_worker_queue_oldest_age(qname, age)
            except Exception:
                pass
            hints[qname] = {
                "scale_up": bool(depth >= depth_thr or age >= age_thr),
                "reasons": [
                    reason
                    for reason, cond in (
                        ("depth", depth >= depth_thr),
                        ("oldest_age", age >= age_thr),
                    )
                    if cond
                ],
                "depth_threshold": depth_thr,
                "oldest_age_threshold_seconds": age_thr,
            }
        return {"ok": True, "stats": stats, "autoscale_hints": hints}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "stats": {"queues": {}}}
