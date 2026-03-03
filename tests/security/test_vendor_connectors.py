from __future__ import annotations

from src.app.security.vendor_connectors import parse_firewall_syslog_line


def test_parse_firewall_syslog_line_kv():
    line = "2026-02-26T11:11:11Z action=deny src=10.0.0.2 dst=8.8.8.8 severity=high event_id=fw-123 device=fw-a"
    out = parse_firewall_syslog_line(line, tenant_id="t1", trace_id="tr-1")
    assert out["event_id"] == "fw-123"
    assert out["tenant_id"] == "t1"
    assert out["trace_id"] == "tr-1"
    assert out["src_ip"] == "10.0.0.2"
    assert out["dst_ip"] == "8.8.8.8"
    assert out["event_type"] == "network"
    assert out["severity"] == "high"
    assert out["confidence"] >= 0.8


def test_parse_firewall_syslog_line_defaults():
    out = parse_firewall_syslog_line("random firewall log line without kv", tenant_id="t2")
    assert out["tenant_id"] == "t2"
    assert out["event_type"] == "network"
    assert out["severity"] in ("medium", "high")
    assert str(out["event_id"]).startswith("fw-")
