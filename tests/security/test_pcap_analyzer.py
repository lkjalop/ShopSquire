from src.app.security.pcap_analyzer import analyze_pcap_payload, correlate_network_findings


def test_pcap_analyzer_fallback_dns_extraction():
    blob = b"random bytes api.example.com xx aaaaaaaaaaaaaaaaaaaaaaaaaaaa.exfil.example.org"
    out = analyze_pcap_payload(pcap_bytes=blob)
    assert out.get("ok") is True
    sig = out.get("signals") or {}
    assert int(sig.get("dns_unique_domains") or 0) >= 1
    assert "top_domains" in out


def test_pcap_correlation_output_shape():
    blob = b"xx c2.example.com aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.evil.example.org"
    out = analyze_pcap_payload(pcap_bytes=blob)
    corr = correlate_network_findings(
        trace_id="trace-ndr-1",
        tenant_id="t1",
        analyzer_output=out,
    )
    assert corr.get("trace_id") == "trace-ndr-1"
    assert corr.get("tenant_id") == "t1"
    assert corr.get("risk_band") in ("low", "medium", "high")
    assert "network_correlated_detection" in corr
