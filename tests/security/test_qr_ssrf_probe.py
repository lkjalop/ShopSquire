from __future__ import annotations

import asyncio

import requests

from src.app.routers.support_complaints import _probe_redirect_chain_now


def test_metadata_qr_is_blocked_before_any_http_request(monkeypatch):
    calls = []
    monkeypatch.setenv("SSRF_ALLOW_PRIVATE", "0")
    monkeypatch.setattr(requests, "request", lambda *a, **k: calls.append((a, k)))
    out = asyncio.run(_probe_redirect_chain_now(
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        timeout_s=0.2,
    ))
    assert out["blocked"] is True
    assert out["policy_action"] == "block"
    assert calls == []


def test_ipv6_loopback_qr_is_blocked_before_any_http_request(monkeypatch):
    calls = []
    monkeypatch.setenv("SSRF_ALLOW_PRIVATE", "0")
    monkeypatch.setattr(requests, "request", lambda *a, **k: calls.append((a, k)))
    out = asyncio.run(_probe_redirect_chain_now("http://[::1]:11434/api/generate", timeout_s=0.2))
    assert out["blocked"] is True
    assert calls == []


def test_private_rfc1918_qr_is_blocked_even_in_local_mode(monkeypatch):
    calls = []
    monkeypatch.setenv("SSRF_ALLOW_PRIVATE", "1")
    monkeypatch.setattr(requests, "request", lambda *a, **k: calls.append((a, k)))
    out = asyncio.run(_probe_redirect_chain_now("http://10.0.0.8/admin", timeout_s=0.2))
    assert out["blocked"] is True
    assert calls == []


def test_dns_answer_change_is_blocked_before_any_http_request(monkeypatch):
    calls = []
    answers = iter([
        [(2, 1, 6, '', ('93.184.216.34', 80))],
        [(2, 1, 6, '', ('127.0.0.1', 80))],
    ])
    monkeypatch.setattr(
        "src.app.routers.support_complaints.socket.getaddrinfo",
        lambda *_args, **_kwargs: next(answers),
    )
    monkeypatch.setattr(requests, "request", lambda *a, **k: calls.append((a, k)))
    out = asyncio.run(_probe_redirect_chain_now("http://rebind.example/probe", timeout_s=0.2))
    assert out["blocked"] is True
    assert "dns_changed" in out["error"]
    assert calls == []
