from __future__ import annotations

import os

from src.app.security.url_guard import validate_outbound_url


def test_blocks_localhost_and_metadata():
    ok1, _ = validate_outbound_url("http://localhost:8080/test")
    ok2, _ = validate_outbound_url("http://169.254.169.254/latest/meta-data")
    assert ok1 is False
    assert ok2 is False


def test_allows_public_https_domain():
    ok, reason = validate_outbound_url("https://example.com/path")
    # DNS may be unavailable in isolated runs; either allow or unresolved with allow.
    assert ok is True or reason in ("ok_unresolved",)


def test_blocks_private_ip_from_dns_resolution(monkeypatch):
    monkeypatch.setenv("SSRF_BLOCK_UNRESOLVED", "1")
    monkeypatch.setenv("SSRF_ALLOW_PRIVATE", "0")

    def _fake_getaddrinfo(*_args, **_kwargs):
        return [(2, 1, 6, "", ("10.1.2.3", 0))]

    import socket

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    ok, reason = validate_outbound_url("https://safe.example/path")
    assert ok is False
    assert reason == "dns_resolved_to_blocked_ip"


def test_blocks_unresolved_in_strict_mode(monkeypatch):
    monkeypatch.setenv("SSRF_BLOCK_UNRESOLVED", "1")

    def _raise(*_args, **_kwargs):
        raise OSError("dns failure")

    import socket

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    ok, reason = validate_outbound_url("https://unknown.invalid/path")
    assert ok is False
    assert reason == "dns_unresolved"

