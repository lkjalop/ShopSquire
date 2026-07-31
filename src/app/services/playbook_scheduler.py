from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.playbook_engine import (
    append_playbook_step,
    complete_playbook_run,
    execute_typed_actions,
    list_playbooks,
    start_playbook_run,
)
from src.app.services.persistence import write_audit_and_event


def _enabled() -> bool:
    return str(os.getenv("PLAYBOOK_SCHEDULER_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def _interval_sec() -> float:
    try:
        return max(10.0, float(os.getenv("PLAYBOOK_SCHEDULER_INTERVAL_SEC", "60") or 60))
    except Exception:
        return 60.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_scheduler_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS playbook_schedule_runs (
                        playbook_id TEXT PRIMARY KEY,
                        last_run_at TEXT,
                        next_run_at TEXT,
                        last_status TEXT,
                        last_run_id TEXT
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def _get_schedule_state(playbook_id: str) -> Dict[str, Any]:
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT playbook_id, last_run_at, next_run_at, last_status, last_run_id
                    FROM playbook_schedule_runs
                    WHERE playbook_id = :playbook_id
                    """
                ),
                {"playbook_id": playbook_id},
            ).fetchone()
        if not row:
            return {}
        return {
            "playbook_id": row[0],
            "last_run_at": row[1],
            "next_run_at": row[2],
            "last_status": row[3],
            "last_run_id": row[4],
        }
    except Exception:
        return {}


def _upsert_schedule_state(playbook_id: str, *, last_run_at: str | None, next_run_at: str | None, last_status: str, last_run_id: str | None) -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO playbook_schedule_runs (playbook_id, last_run_at, next_run_at, last_status, last_run_id)
                    VALUES (:playbook_id, :last_run_at, :next_run_at, :last_status, :last_run_id)
                    ON CONFLICT(playbook_id) DO UPDATE SET
                        last_run_at = excluded.last_run_at,
                        next_run_at = excluded.next_run_at,
                        last_status = excluded.last_status,
                        last_run_id = excluded.last_run_id
                    """
                ),
                {
                    "playbook_id": playbook_id,
                    "last_run_at": last_run_at,
                    "next_run_at": next_run_at,
                    "last_status": last_status,
                    "last_run_id": last_run_id,
                },
            )
            db.commit()
    except Exception:
        pass


def _parse_next_due(
    last_next: str | None,
    interval_minutes: int,
    *,
    fallback_now: datetime | None = None,
) -> datetime:
    if last_next:
        try:
            dt = datetime.fromisoformat(str(last_next).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return fallback_now or _utc_now()


def run_scheduled_playbooks_cycle() -> Dict[str, Any]:
    _ensure_scheduler_table()
    playbooks = list_playbooks(include_disabled=False)
    now = _utc_now()
    out: Dict[str, Any] = {"checked": 0, "triggered": 0, "runs": []}
    for pb in playbooks:
        schedule = pb.get("schedule") if isinstance(pb.get("schedule"), dict) else {}
        if not schedule:
            continue
        if str(schedule.get("enabled", True)).strip().lower() in ("0", "false", "no", "off"):
            continue
        out["checked"] += 1
        pbid = str(pb.get("id") or "").strip()
        if not pbid:
            continue
        interval_minutes = max(1, int(schedule.get("interval_minutes") or 1440))
        st = _get_schedule_state(pbid)
        next_due = _parse_next_due(
            st.get("next_run_at"),
            interval_minutes,
            fallback_now=now,
        )
        if now < next_due:
            continue

        owner = str(schedule.get("owner") or "Playbook_Scheduler")
        run_id = start_playbook_run(
            trace_id=f"schedule:{pbid}",
            decision_id=f"schedule:{pbid}",
            tenant_id=str(schedule.get("tenant_id") or "default"),
            playbook=pb,
            owner=owner,
            metadata={"scheduled": True, "interval_minutes": interval_minutes},
        )
        status = "completed"
        if not run_id:
            status = "failed"
        else:
            try:
                append_playbook_step(run_id=run_id, event_type="scheduled_trigger", status="completed", evidence={"schedule": schedule})
                actions = pb.get("actions") if isinstance(pb.get("actions"), list) else []
                exec_out = execute_typed_actions(run_id=run_id, actions=actions, context={"channel": "scheduler", "scheduled": True})
                append_playbook_step(run_id=run_id, event_type="scheduled_actions", status="completed", evidence={"result": exec_out})
                if exec_out.get("failed"):
                    status = "failed"
                complete_playbook_run(run_id=run_id, status=("failed" if status == "failed" else "completed"), outcome="scheduled_run")
            except Exception:
                status = "failed"
                try:
                    complete_playbook_run(run_id=run_id, status="failed", outcome="scheduled_run_error")
                except Exception:
                    pass
        next_run = now + timedelta(minutes=interval_minutes)
        _upsert_schedule_state(
            pbid,
            last_run_at=now.isoformat(),
            next_run_at=next_run.isoformat(),
            last_status=status,
            last_run_id=run_id,
        )
        out["triggered"] += 1
        out["runs"].append({"playbook_id": pbid, "run_id": run_id, "status": status, "next_run_at": next_run.isoformat()})
    try:
        write_audit_and_event(
            decision_id="system:playbook_scheduler",
            action="playbook_schedule_cycle",
            actor="system.scheduler",
            metadata={"checked": out["checked"], "triggered": out["triggered"]},
        )
    except Exception:
        pass
    return out


def start_playbook_scheduler(app=None):
    if not _enabled():
        return None
    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                run_scheduled_playbooks_cycle()
            except Exception:
                pass
            stop_event.wait(timeout=_interval_sec())

    th = threading.Thread(target=_loop, daemon=True, name="playbook-scheduler")
    th.start()
    try:
        if app is not None and hasattr(app, "state"):
            app.state.playbook_scheduler_stop = stop_event
            app.state.playbook_scheduler_thread = th
    except Exception:
        pass
    return th


def stop_playbook_scheduler(app=None):
    try:
        ev = getattr(app.state, "playbook_scheduler_stop", None) if app is not None else None
        th = getattr(app.state, "playbook_scheduler_thread", None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
    except Exception:
        pass
