from __future__ import annotations

from src.app.workers.celery_app import celery_app


@celery_app.task(name="src.app.tasks.incident_ops_tasks.check_incident_sla_breaches")
def check_incident_sla_breaches() -> dict:
    """Periodic SLA breach scan for escalation incidents."""
    try:
        from src.app.services.incident_sla_scheduler import run_cycle

        return run_cycle() or {"checked": 0, "breached": 0}
    except Exception as exc:
        return {"checked": 0, "breached": 0, "error": str(exc)}


@celery_app.task(name="src.app.tasks.incident_ops_tasks.trace_broker_recovery")
def trace_broker_recovery() -> dict:
    """Best-effort decision trace broker replay/recovery for enterprise ops."""
    try:
        import asyncio
        from src.app.services.trace_broker import recover_pending, replay_recent

        async def _run() -> dict:
            recovered = await recover_pending(max_messages=200)
            replayed = await replay_recent(count=200)
            return {"recovered": recovered, "replayed": replayed}

        return asyncio.run(_run())
    except Exception as exc:
        return {"error": str(exc)}
