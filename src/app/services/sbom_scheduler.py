from __future__ import annotations

import os
import threading

from src.app.security.supply_chain_automation import correlate_local_sboms


_DEF_STOP_ATTR = "sbom_scheduler_stop"
_DEF_THREAD_ATTR = "sbom_scheduler_thread"


def _enabled() -> bool:
    return str(os.getenv("SUPPLY_CHAIN_SBOM_AUTOMATION_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def _interval_sec() -> float:
    try:
        return max(300.0, float(os.getenv("SUPPLY_CHAIN_SBOM_AUTOMATION_INTERVAL_SEC", "86400") or 86400))
    except Exception:
        return 86400.0


def run_cycle(*, tenant_id: str | None = None):
    return correlate_local_sboms(tenant_id=tenant_id)


def start_sbom_scheduler(app=None):
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

    th = threading.Thread(target=_loop, daemon=True, name="sbom-correlation-scheduler")
    th.start()
    try:
        if app is not None and hasattr(app, "state"):
            setattr(app.state, _DEF_STOP_ATTR, stop_event)
            setattr(app.state, _DEF_THREAD_ATTR, th)
    except Exception:
        pass
    return th


def stop_sbom_scheduler(app=None):
    try:
        ev = getattr(app.state, _DEF_STOP_ATTR, None) if app is not None else None
        th = getattr(app.state, _DEF_THREAD_ATTR, None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
    except Exception:
        pass
