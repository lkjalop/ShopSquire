from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _enabled() -> bool:
    raw = os.getenv("MTLS_CERT_MONITOR_ENABLED")
    if raw is not None:
        return str(raw).lower() in ("1", "true", "yes")
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env in ("prod", "production", "staging")


def _cert_dir() -> str:
    return str(os.getenv("MTLS_CERT_DIR", "config/tls/certs") or "config/tls/certs")


def _warn_days() -> int:
    try:
        return max(1, int(os.getenv("MTLS_CERT_WARN_DAYS", "21") or 21))
    except Exception:
        return 21


def _interval_sec() -> float:
    try:
        return max(300.0, float(os.getenv("MTLS_CERT_MONITOR_INTERVAL_SEC", "3600") or 3600))
    except Exception:
        return 3600.0


def _cert_expiry_days(path: Path) -> float | None:
    try:
        from cryptography import x509  # type: ignore

        raw = path.read_bytes()
        cert = x509.load_pem_x509_certificate(raw)
        end = cert.not_valid_after
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (end - now).total_seconds() / 86400.0
    except Exception:
        return None


def check_mtls_cert_expiry() -> Dict[str, Any]:
    base = Path(_cert_dir())
    out: List[Dict[str, Any]] = []
    if not base.exists() or not base.is_dir():
        return {"ok": False, "error": "cert_dir_missing", "path": str(base)}

    for p in sorted(base.glob("*.crt")):
        days = _cert_expiry_days(p)
        out.append(
            {
                "cert": p.name,
                "expires_in_days": round(float(days), 2) if days is not None else None,
                "expiring_soon": bool(days is not None and days <= float(_warn_days())),
            }
        )

    expiring = [x for x in out if x.get("expiring_soon")]
    return {
        "ok": True,
        "path": str(base),
        "warn_days": _warn_days(),
        "checked": len(out),
        "expiring": len(expiring),
        "certs": out,
    }


def _emit_expiry_alert(report: Dict[str, Any]) -> None:
    try:
        from src.app.observability.metrics import record_incident_alert

        sev = "p1" if int(report.get("expiring") or 0) > 0 else "p3"
        record_incident_alert("mtls_cert_expiry", sev)
    except Exception:
        pass


def run_mtls_cert_monitor_cycle() -> Dict[str, Any]:
    report = check_mtls_cert_expiry()
    if report.get("ok") and int(report.get("expiring") or 0) > 0:
        _emit_expiry_alert(report)
    return report


def start_mtls_cert_monitor(app=None):
    if not _enabled():
        return None
    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                run_mtls_cert_monitor_cycle()
            except Exception:
                pass
            stop_event.wait(timeout=_interval_sec())

    th = threading.Thread(target=_loop, daemon=True, name="mtls-cert-monitor")
    th.start()
    try:
        if app is not None and hasattr(app, "state"):
            app.state.mtls_cert_monitor_stop = stop_event
            app.state.mtls_cert_monitor_thread = th
    except Exception:
        pass
    return th


def stop_mtls_cert_monitor(app=None):
    try:
        ev = getattr(app.state, "mtls_cert_monitor_stop", None) if app is not None else None
        th = getattr(app.state, "mtls_cert_monitor_thread", None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
    except Exception:
        pass
