from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict

from src.app.services.playbook_engine import reprocess_playbook_dlq
from src.app.services.persistence import write_audit_and_event


def _enabled() -> bool:
    return str(os.getenv("PLAYBOOK_DLQ_REPROCESSOR_ENABLED", "0") or "0").lower() in ("1", "true", "yes")


def _interval_sec() -> float:
    try:
        return max(5.0, float(os.getenv("PLAYBOOK_DLQ_REPROCESS_INTERVAL_SEC", "60") or 60))
    except Exception:
        return 60.0


def _batch_cap() -> int:
    try:
        return max(1, min(int(os.getenv("PLAYBOOK_DLQ_REPROCESS_BATCH_CAP", "100") or 100), 500))
    except Exception:
        return 100


def _max_runtime_sec() -> float:
    try:
        return max(1.0, min(float(os.getenv("PLAYBOOK_DLQ_REPROCESS_MAX_RUNTIME_SEC", "20") or 20), 120.0))
    except Exception:
        return 20.0


def run_dlq_reprocessor_cycle() -> Dict[str, Any]:
    started = time.time()
    cap = _batch_cap()
    summary = reprocess_playbook_dlq(limit=cap)
    elapsed_ms = int((time.time() - started) * 1000)
    safe = {
        "cap": cap,
        "elapsed_ms": elapsed_ms,
        "picked": int(summary.get("picked") or 0),
        "reprocessed": int(summary.get("reprocessed") or 0),
        "failed": int(summary.get("failed") or 0),
        "safety": {
            "max_runtime_sec": _max_runtime_sec(),
            "interval_sec": _interval_sec(),
        },
    }
    try:
        write_audit_and_event(
            decision_id="system:playbook_dlq",
            action="playbook_dlq_reprocess_cycle",
            actor="system.scheduler",
            metadata=safe,
        )
    except Exception:
        pass
    return safe


def start_dlq_scheduler(app=None):
    if not _enabled():
        return None
    stop_event = threading.Event()

    def _loop():
        interval = _interval_sec()
        max_runtime = _max_runtime_sec()
        while not stop_event.is_set():
            t0 = time.time()
            try:
                run_dlq_reprocessor_cycle()
            except Exception:
                pass
            elapsed = time.time() - t0
            # safety cap: if a cycle overruns, sleep minimally and continue.
            sleep_s = max(1.0, interval - min(elapsed, max_runtime))
            stop_event.wait(timeout=sleep_s)

    th = threading.Thread(target=_loop, daemon=True, name="playbook-dlq-scheduler")
    th.start()
    try:
        if app is not None and hasattr(app, "state"):
            app.state.playbook_dlq_scheduler_stop = stop_event
            app.state.playbook_dlq_scheduler_thread = th
    except Exception:
        pass
    return th


def stop_dlq_scheduler(app=None):
    try:
        ev = getattr(app.state, "playbook_dlq_scheduler_stop", None) if app is not None else None
        th = getattr(app.state, "playbook_dlq_scheduler_thread", None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
    except Exception:
        pass
