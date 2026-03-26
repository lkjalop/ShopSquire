from __future__ import annotations

from src.app.security import qr_legitimacy as mod


def test_qr_legitimacy_heuristic_suspicious_without_intel(monkeypatch):
    monkeypatch.setenv("QR_THREAT_INTEL_ENABLED", "0")
    out = mod.derive_qr_legitimacy_details(
        {
            "qr_code_detected": True,
            "qr_payloads": [{"data": "https://example.com", "type": "QRCODE"}],
        },
        policy_route="allow",
    )
    assert out["destination_url"] == "https://example.com"
    assert out["reputation_verdict"] == "suspicious"
    assert out["intel_pending"] is False


def test_qr_legitimacy_cached_intel_overrides_to_malicious(monkeypatch):
    monkeypatch.setenv("QR_THREAT_INTEL_ENABLED", "1")
    monkeypatch.setenv("QR_THREAT_INTEL_ASYNC", "1")
    monkeypatch.setattr(mod, "get_cached_url_threat_intel", lambda _u: {"risk": 0.93, "malicious": True, "sources": [{"source": "urlhaus"}]})
    monkeypatch.setattr(mod, "enqueue_url_threat_intel", lambda _u: {"queued": False})
    out = mod.derive_qr_legitimacy_details(
        {
            "qr_code_detected": True,
            "qr_payloads": [{"data": "https://bad.example", "type": "QRCODE"}],
        },
        policy_route="allow",
    )
    assert out["reputation_verdict"] == "malicious"
    assert out["intel_risk"] == 0.93
    assert "urlhaus" in (out.get("intel_sources") or [])


def test_qr_legitimacy_async_pending_when_no_cache(monkeypatch):
    monkeypatch.setenv("QR_THREAT_INTEL_ENABLED", "1")
    monkeypatch.setenv("QR_THREAT_INTEL_ASYNC", "1")
    monkeypatch.setattr(mod, "get_cached_url_threat_intel", lambda _u: None)
    monkeypatch.setattr(mod, "enqueue_url_threat_intel", lambda _u: {"queued": True})
    out = mod.derive_qr_legitimacy_details(
        {"qr_payloads": [{"data": "https://pending.example"}]},
        policy_route="allow",
    )
    assert out["intel_pending"] is True
    assert out["intel_risk"] is None


def test_qr_legitimacy_treats_benign_qr_as_benign(monkeypatch):
    monkeypatch.setenv("QR_THREAT_INTEL_ENABLED", "0")
    out = mod.derive_qr_legitimacy_details(
        {
            "qr_code_detected": True,
            "qr_benign_detected": True,
            "qr_payloads": [{"data": "mailto:support@example.com", "type": "QRCODE"}],
        },
        policy_route="allow",
    )
    assert out["reputation_verdict"] == "benign"
