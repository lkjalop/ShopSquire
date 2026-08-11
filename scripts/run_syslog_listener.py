from __future__ import annotations

import os
import signal
import time
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.services.syslog_listener import start_syslog_listener, stop_syslog_listener  # noqa: E402


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    # Bind to a local trusted forwarder by default. Raw UDP has no sender identity.
    host = str(os.getenv("SYSLOG_LISTENER_HOST", "127.0.0.1") or "127.0.0.1")
    udp_port = int(float(os.getenv("SYSLOG_LISTENER_UDP_PORT", "5514") or 5514))
    tcp_port = int(float(os.getenv("SYSLOG_LISTENER_TCP_PORT", "5514") or 5514))
    tenant_id = str(os.getenv("SYSLOG_LISTENER_TENANT_ID", "default") or "default")
    trace_id = str(os.getenv("SYSLOG_LISTENER_TRACE_ID", "") or "").strip() or None
    enable_udp = _bool_env("SYSLOG_LISTENER_ENABLE_UDP", False)
    enable_tcp = _bool_env("SYSLOG_LISTENER_ENABLE_TCP", True)
    if not enable_udp and not enable_tcp:
        print({"status": "disabled", "reason": "both_tcp_udp_disabled"})
        return 0

    handle = start_syslog_listener(
        host=host,
        udp_port=udp_port,
        tcp_port=tcp_port,
        tenant_id=tenant_id,
        trace_id=trace_id,
        enable_udp=enable_udp,
        enable_tcp=enable_tcp,
    )
    print(
        {
            "status": "running",
            "host": host,
            "udp_port": udp_port if enable_udp else None,
            "tcp_port": tcp_port if enable_tcp else None,
            "tenant_id": tenant_id,
        }
    )

    stop = {"flag": False}

    def _on_sig(_sig, _frm):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)
    try:
        while not stop["flag"]:
            time.sleep(0.5)
    finally:
        stop_syslog_listener(handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
