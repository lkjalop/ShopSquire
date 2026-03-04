from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.incident_alert_adapters import dispatch_incident_alert
from src.app.services.decision_log import log_trace_event


_DEF_STOP_ATTR = "incident_sla_scheduler_stop"
_DEF_THREAD_ATTR = "incident_sla_scheduler_thread"


def _enabled() -> bool:
    return str(os.getenv("INCIDENT_SLA_SCHEDULER_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes", "on")


def _interval_sec() -> float:
    try:
        return max(15.0, float(os.getenv("INCIDENT_SLA_SCHEDULER_INTERVAL_SEC", "30") or 30))
    except Exception:
        return 30.0


def _repeat_interval_sec() -> int:
    try:
        hours = float(os.getenv("INCIDENT_SLA_BREACH_REPEAT_HOURS", "4") or 4)
    except Exception:
        hours = 4.0
    return max(900, int(hours * 3600))


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _ensure_columns() -> None:
    try:
        with db_session() as db:
            for stmt in [
                "ALTER TABLE incidents ADD COLUMN sla_status TEXT",
                "ALTER TABLE incidents ADD COLUMN sla_due_at TEXT",
                "ALTER TABLE incidents ADD COLUMN sla_breach_alerted_at TEXT",
            ]:
                try:
                    db.execute(text(stmt))
                except Exception:
                    pass
            db.commit()
    except Exception:
        pass


def run_cycle() -> dict:
    _ensure_columns()
    now = datetime.now(timezone.utc)
    checked = 0
    breached = 0
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    "SELECT id, severity, title, description, status, sla_due_at, sla_status, sla_breach_alerted_at FROM incidents "
                    "WHERE status IN ('open', 'review', 'triaged') ORDER BY created_at DESC LIMIT 1000"
                )
            ).fetchall()
            for r in rows or []:
                checked += 1
                iid = str(r[0])
                severity = str(r[1] or "warn")
                title = str(r[2] or "")
                description = str(r[3] or "")
                status = str(r[4] or "open")
                due = _parse_ts(str(r[5]) if r[5] else None)
                st = str(r[6] or "").lower()
                alerted = _parse_ts(str(r[7]) if r[7] else None)
                if due and due < now and st not in ("breached", "met"):
                    db.execute(text("UPDATE incidents SET sla_status = 'breached' WHERE id = :id"), {"id": iid})
                    breached += 1
                    st = "breached"
                repeat_due = bool(alerted is None or int((now - alerted).total_seconds()) >= _repeat_interval_sec())
                if due and due < now and st == "breached" and repeat_due:
                    out = dispatch_incident_alert(
                        "incident_sla_breached",
                        {
                            "id": iid,
                            "severity": severity,
                            "title": title,
                            "description": description,
                            "status": status,
                            "sla_due_at": due.isoformat(),
                        },
                        details={
                            "source": "incident_sla_scheduler",
                            "repeat_alert": bool(alerted),
                            "repeat_interval_seconds": _repeat_interval_sec(),
                        },
                    )
                    if bool(out.get("sent_total")):
                        ts = now.isoformat()
                        db.execute(
                            text("UPDATE incidents SET sla_breach_alerted_at = :ts WHERE id = :id"),
                            {"id": iid, "ts": ts},
                        )
                    try:
                        log_trace_event(
                            trace_id=iid,
                            event_type="incident_alert_dispatch",
                            source_type="agent",
                            source_id="Incident_SLA_Scheduler",
                            target_type="system",
                            target_id=None,
                            payload={
                                "event_type": "incident_sla_breached",
                                "dispatch": out,
                                "incident_id": iid,
                                "sla_due_at": due.isoformat(),
                                "repeat_alert": bool(alerted),
                            },
                        )
                    except Exception:
                        pass
            db.commit()
    except Exception:
        pass
    return {"checked": checked, "breached": breached}


def start_incident_sla_scheduler(app=None):
    if not _enabled():
        return None
    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                run_cycle()
            except Exception:
                pass
            stop_event.wait(timeout=_interval_sec())

    th = threading.Thread(target=_loop, daemon=True, name="incident-sla-scheduler")
    th.start()
    try:
        if app is not None and hasattr(app, "state"):
            setattr(app.state, _DEF_STOP_ATTR, stop_event)
            setattr(app.state, _DEF_THREAD_ATTR, th)
    except Exception:
        pass
    return th


def stop_incident_sla_scheduler(app=None):
    try:
        ev = getattr(app.state, _DEF_STOP_ATTR, None) if app is not None else None
        th = getattr(app.state, _DEF_THREAD_ATTR, None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
    except Exception:
        pass
