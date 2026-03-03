from __future__ import annotations

from types import SimpleNamespace


def _req(ip: str, headers: dict[str, str]):
    return SimpleNamespace(
        client=SimpleNamespace(host=ip),
        headers=headers,
        state=SimpleNamespace(),
    )


def test_extract_tls_fingerprints_trusted_proxy(monkeypatch):
    from src.app.security.tls_fingerprint_middleware import extract_tls_fingerprints_from_request

    monkeypatch.setenv("TLS_FINGERPRINT_TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("TLS_FINGERPRINT_TRUST_FAIL_CLOSED", "1")
    r = _req(
        "10.1.2.3",
        {
            "x-ja3-hash": "0123456789abcdef0123456789abcdef",
            "x-ja4-hash": "t13d1516h2_8daaf6152771_5fb2d1f77f52",
        },
    )
    out = extract_tls_fingerprints_from_request(r)
    assert out.get("trusted_proxy_source") is True
    assert out.get("ja3_hash") == "0123456789abcdef0123456789abcdef"
    assert out.get("ja4_hash") == "t13d1516h2_8daaf6152771_5fb2d1f77f52"


def test_extract_tls_fingerprints_untrusted_proxy_fail_closed(monkeypatch):
    from src.app.security.tls_fingerprint_middleware import extract_tls_fingerprints_from_request

    monkeypatch.setenv("TLS_FINGERPRINT_TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("TLS_FINGERPRINT_TRUST_FAIL_CLOSED", "1")
    r = _req(
        "203.0.113.10",
        {
            "x-ja3-hash": "0123456789abcdef0123456789abcdef",
            "x-ja4-hash": "t13d1516h2_8daaf6152771_5fb2d1f77f52",
        },
    )
    out = extract_tls_fingerprints_from_request(r)
    assert out.get("trusted_proxy_source") is False
    assert out.get("ja3_hash") == ""
    assert out.get("ja4_hash") == ""

