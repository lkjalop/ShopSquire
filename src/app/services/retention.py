from __future__ import annotations

import asyncio
import os
from typing import Optional

from sqlalchemy import text

from src.app.models.db import db_session


def _get_days(env_key: str, default_days: int) -> int:
    try:
        return int(os.getenv(env_key, str(default_days)))
    except Exception:
        return default_days


def _cleanup_sql(dialect: str, table: str, column: str, days: int) -> str:
    if "postgres" in dialect:
        return f"DELETE FROM {table} WHERE {column} < NOW() - INTERVAL '{days} days'"
    # sqlite / others
    return f"DELETE FROM {table} WHERE {column} < datetime('now', '-{days} days')"


def cleanup_once() -> None:
    enabled = str(os.getenv("RETENTION_CLEANUP_ENABLED", "1")).lower() in ("1", "true", "yes")
    if not enabled:
        return
    audit_days = _get_days("AUDIT_LOG_DAYS", 90)
    evidence_days = _get_days("CV_EVIDENCE_DAYS", 30)
    try:
        with db_session() as db:
            dialect = getattr(db.bind.dialect, "name", "")
            # Ensure helpful indexes exist for retention queries (best-effort)
            try:
                if "postgres" in dialect:
                    db.execute(text("CREATE INDEX IF NOT EXISTS idx_decision_logs_valid_from ON decision_logs(valid_from)"))
                    db.execute(text("CREATE INDEX IF NOT EXISTS idx_decision_trace_events_created_at ON decision_trace_events(created_at)"))
                else:
                    db.execute(text("CREATE INDEX IF NOT EXISTS idx_decision_logs_valid_from ON decision_logs(valid_from)"))
                    db.execute(text("CREATE INDEX IF NOT EXISTS idx_decision_trace_events_created_at ON decision_trace_events(created_at)"))
            except Exception:
                pass
            try:
                db.execute(text(_cleanup_sql(dialect, "decision_trace_events", "created_at", audit_days)))
            except Exception:
                pass
            try:
                db.execute(text(_cleanup_sql(dialect, "decision_logs", "valid_from", audit_days)))
            except Exception:
                pass
            try:
                db.execute(text(_cleanup_sql(dialect, "security_events", "event_time", audit_days)))
            except Exception:
                pass
            try:
                db.execute(text(_cleanup_sql(dialect, "evidence_bundles", "created_at", evidence_days)))
            except Exception:
                pass
            # Per-tenant overrides when configured
            try:
                policies = db.execute(text("SELECT tenant_id, audit_days, evidence_days FROM retention_policies")).fetchall()
                for p in policies or []:
                    tid = p[0]
                    audit_d = int(p[1] or audit_days)
                    evidence_d = int(p[2] or evidence_days)
                    try:
                        db.execute(text(_cleanup_sql(dialect, "decision_logs", "valid_from", audit_d) + " AND tenant_id = :tid"), {"tid": tid})
                    except Exception:
                        pass
                    try:
                        db.execute(text(_cleanup_sql(dialect, "evidence_bundles", "created_at", evidence_d) + " AND tenant_id = :tid"), {"tid": tid})
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
    except Exception:
        return


async def retention_loop(poll_seconds: int = 3600) -> None:
    while True:
        try:
            cleanup_once()
        except Exception:
            pass
        await asyncio.sleep(poll_seconds)


def start_retention_loop(app, poll_seconds: Optional[int] = None) -> Optional[asyncio.Task]:
    try:
        loop = asyncio.get_running_loop()
    except Exception:
        return None
    interval = poll_seconds
    if interval is None:
        try:
            interval = int(os.getenv("RETENTION_POLL_SECONDS", "3600"))
        except Exception:
            interval = 3600
    task = loop.create_task(retention_loop(interval))
    app.state.retention_task = task
    return task


def stop_retention_loop(app) -> None:
    try:
        task = getattr(app.state, "retention_task", None)
        if task and not task.done():
            task.cancel()
    except Exception:
        pass
