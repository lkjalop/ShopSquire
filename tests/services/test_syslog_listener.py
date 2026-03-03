from __future__ import annotations

from src.app.services.syslog_listener import SyslogIngestService


def test_syslog_ingest_service_ingests_line():
    svc = SyslogIngestService(tenant_id="tenant-syslog", trace_id="trace-syslog-1")
    out = svc.ingest_line("2026-02-26T12:00:00Z action=deny src=10.0.0.3 dst=8.8.8.8 severity=high event_id=fw-sys-1")
    assert out.get("ok") is True
    assert (out.get("canonical") or {}).get("tenant_id") == "tenant-syslog"
    assert (out.get("canonical") or {}).get("trace_id") == "trace-syslog-1"
    assert (out.get("policy") or {}).get("action") in ("challenge", "escalate", "block")
