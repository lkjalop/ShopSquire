from __future__ import annotations

import os
import threading
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from src.app.models.db import db_session, get_engine
from src.app.services.incident_alert_adapters import dispatch_incident_alert
from src.app.services.decision_log import log_trace_event


_DEF_STOP_ATTR = "incident_sla_scheduler_stop"
_DEF_THREAD_ATTR = "incident_sla_scheduler_thread"
_WORKER_LOCK = threading.RLock()
_LOGGER = logging.getLogger(__name__)


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


@contextmanager
def _session(engine):
    if engine is None:
        with db_session() as db:
            yield db
    else:
        from src.app.platform.tenant_session import bind_session_tenant

        with Session(engine) as db:
            bind_session_tenant(db)
            yield db


def _ensure_columns(engine=None) -> None:
    # Legacy SQLite fixtures need these columns. PostgreSQL is migration-owned.
    # Repeated failing ALTERs can themselves hold locks or abort a transaction.
    with _session(engine) as db:
        bind = db.get_bind()
        if bind.dialect.name != "sqlite":
            return
        columns = {column["name"] for column in inspect(bind).get_columns("incidents")}
        for name in ("sla_status", "sla_due_at", "sla_breach_alerted_at"):
            if name not in columns:
                db.execute(text(f"ALTER TABLE incidents ADD COLUMN {name} TEXT"))
        db.commit()


def run_cycle(*, engine=None) -> dict:
    now = datetime.now(timezone.utc)
    checked = 0
    breached = 0
    pending = []
    errors = 0
    try:
        _ensure_columns(engine)
        with _session(engine) as db:
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
                    pending.append(({
                        "id": iid, "severity": severity, "title": title,
                        "description": description, "status": status,
                        "sla_due_at": due.isoformat(),
                    }, bool(alerted)))
            db.commit()
    except Exception as exc:
        _LOGGER.error("Incident SLA database cycle failed: %s", type(exc).__name__)
        return {"checked": checked, "breached": breached, "ok": False, "errors": 1}

    # Alert adapters and trace persistence may open their own write sessions.
    # Neither may run while this cycle owns a transaction or SQLite writer lock.
    for incident, repeat_alert in pending:
        try:
            out = dispatch_incident_alert(
                "incident_sla_breached", incident,
                details={"source": "incident_sla_scheduler", "repeat_alert": repeat_alert,
                         "repeat_interval_seconds": _repeat_interval_sec()},
            )
            if bool(out.get("sent_total")):
                with _session(engine) as db:
                    db.execute(
                        text("UPDATE incidents SET sla_breach_alerted_at = :ts WHERE id = :id"),
                        {"id": incident["id"], "ts": now.isoformat()},
                    )
                    db.commit()
            log_trace_event(
                trace_id=incident["id"], event_type="incident_alert_dispatch",
                source_type="agent", source_id="Incident_SLA_Scheduler",
                target_type="system", target_id=None,
                payload={"event_type": "incident_sla_breached", "dispatch": out,
                         "incident_id": incident["id"], "sla_due_at": incident["sla_due_at"],
                         "repeat_alert": repeat_alert},
            )
        except Exception as exc:
            errors += 1
            _LOGGER.error("Incident SLA delivery/audit failed: %s", type(exc).__name__)
    return {"checked": checked, "breached": breached, "ok": errors == 0, "errors": errors}


def start_incident_sla_scheduler(app=None):
    if not _enabled():
        return None
    if app is None or not hasattr(app, "state"):
        raise ValueError("Incident SLA scheduler requires an application owner")
    with _WORKER_LOCK:
        previous = getattr(app.state, _DEF_THREAD_ATTR, None)
        if previous is not None and previous.is_alive():
            if getattr(app.state, _DEF_STOP_ATTR).is_set():
                raise RuntimeError("Incident SLA scheduler is still stopping")
            return previous
        stop_event = threading.Event()
        engine = getattr(app.state, "engine", None)
        if engine is None:
            engine = get_engine()

        def _loop():
            while not stop_event.is_set():
                try:
                    run_cycle(engine=engine)
                except Exception as exc:
                    _LOGGER.error("Incident SLA worker failed: %s", type(exc).__name__)
                stop_event.wait(timeout=_interval_sec())

        th = threading.Thread(target=_loop, daemon=True, name="incident-sla-scheduler")
        setattr(app.state, _DEF_STOP_ATTR, stop_event)
        setattr(app.state, _DEF_THREAD_ATTR, th)
        th.start()
        return th


def stop_incident_sla_scheduler(app=None):
    with _WORKER_LOCK:
        ev = getattr(app.state, _DEF_STOP_ATTR, None) if app is not None else None
        th = getattr(app.state, _DEF_THREAD_ATTR, None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
            if th.is_alive():
                raise RuntimeError("Incident SLA scheduler did not stop within 2 seconds")
        if app is not None:
            setattr(app.state, _DEF_THREAD_ATTR, None)
            setattr(app.state, _DEF_STOP_ATTR, None)
