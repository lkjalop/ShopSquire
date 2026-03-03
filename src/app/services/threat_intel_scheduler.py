from __future__ import annotations

import os
import threading

from src.app.security.threat_intel_automation import sync_all_automated_feeds


_DEF_STOP_ATTR = "threat_intel_scheduler_stop"
_DEF_THREAD_ATTR = "threat_intel_scheduler_thread"


def _enabled() -> bool:
    return str(os.getenv("THREAT_INTEL_AUTOMATION_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def _interval_sec() -> float:
    try:
        return max(60.0, float(os.getenv("THREAT_INTEL_AUTOMATION_INTERVAL_SEC", "900") or 900))
    except Exception:
        return 900.0


def run_cycle(*, tenant_id: str | None = None):
    return sync_all_automated_feeds(tenant_id=tenant_id)


def start_threat_intel_scheduler(app=None):
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

    th = threading.Thread(target=_loop, daemon=True, name="threat-intel-scheduler")
    th.start()
    try:
        if app is not None and hasattr(app, "state"):
            setattr(app.state, _DEF_STOP_ATTR, stop_event)
            setattr(app.state, _DEF_THREAD_ATTR, th)
    except Exception:
        pass
    return th


def stop_threat_intel_scheduler(app=None):
    try:
        ev = getattr(app.state, _DEF_STOP_ATTR, None) if app is not None else None
        th = getattr(app.state, _DEF_THREAD_ATTR, None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
    except Exception:
        pass
