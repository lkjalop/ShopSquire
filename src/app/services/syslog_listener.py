from __future__ import annotations

import socket
import threading
import time
from typing import Any, Dict, List

from src.app.security.vendor_connectors import parse_firewall_syslog_line
from src.app.security.security_event_ingest import ingest_security_event


class SyslogIngestService:
    def __init__(self, tenant_id: str = "default", trace_id: str | None = None):
        self.tenant_id = str(tenant_id or "default")
        self.trace_id = str(trace_id or "").strip() or None

    def ingest_line(self, line: str) -> Dict[str, Any]:
        event = parse_firewall_syslog_line(str(line or ""), tenant_id=self.tenant_id, trace_id=self.trace_id)
        return ingest_security_event(vendor="firewall", payload=event)


def _recv_udp_loop(host: str, port: int, service: SyslogIngestService, stop_event: threading.Event, max_bytes: int = 65535):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, int(port)))
    sock.settimeout(1.0)
    try:
        while not stop_event.is_set():
            try:
                data, _addr = sock.recvfrom(max_bytes)
            except socket.timeout:
                continue
            except Exception:
                time.sleep(0.1)
                continue
            try:
                msg = data.decode("utf-8", errors="replace").strip()
                if msg:
                    service.ingest_line(msg)
            except Exception:
                continue
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _recv_tcp_loop(host: str, port: int, service: SyslogIngestService, stop_event: threading.Event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, int(port)))
    sock.listen(32)
    sock.settimeout(1.0)
    try:
        while not stop_event.is_set():
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except Exception:
                time.sleep(0.1)
                continue
            conn.settimeout(1.0)
            with conn:
                buf = b""
                while not stop_event.is_set():
                    try:
                        chunk = conn.recv(4096)
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        msg = line.decode("utf-8", errors="replace").strip()
                        if msg:
                            try:
                                service.ingest_line(msg)
                            except Exception:
                                pass
    finally:
        try:
            sock.close()
        except Exception:
            pass


def start_syslog_listener(
    *,
    host: str = "127.0.0.1",
    udp_port: int = 5514,
    tcp_port: int = 5514,
    tenant_id: str = "default",
    trace_id: str | None = None,
    enable_udp: bool = False,
    enable_tcp: bool = True,
) -> Dict[str, Any]:
    stop_event = threading.Event()
    service = SyslogIngestService(tenant_id=tenant_id, trace_id=trace_id)
    threads: List[threading.Thread] = []
    if enable_udp:
        t = threading.Thread(target=_recv_udp_loop, args=(host, int(udp_port), service, stop_event), daemon=True)
        t.start()
        threads.append(t)
    if enable_tcp:
        t = threading.Thread(target=_recv_tcp_loop, args=(host, int(tcp_port), service, stop_event), daemon=True)
        t.start()
        threads.append(t)
    return {"stop_event": stop_event, "threads": threads}


def stop_syslog_listener(handle: Dict[str, Any], timeout: float = 2.0) -> None:
    if not isinstance(handle, dict):
        return
    stop_event = handle.get("stop_event")
    threads = handle.get("threads") or []
    try:
        if stop_event is not None:
            stop_event.set()
    except Exception:
        pass
    for t in threads:
        try:
            t.join(timeout=timeout)
        except Exception:
            pass
