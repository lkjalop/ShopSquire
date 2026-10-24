"""Removing a test egress guard must restore methods, not retain old closures."""
import httpx
from src.app.security import egress_allowlist as egress


def test_guard_roundtrip_restores_sync_and_async_methods(monkeypatch):
    egress.unpatch_httpx_egress_guard()
    before=(httpx.Client.send,httpx.AsyncClient.send)
    monkeypatch.setenv('EGRESS_ALLOWLIST_ENABLED','1')
    guard=egress.EgressDomainGuard(strict=True)
    try:
        egress.patch_httpx_egress_guard(guard)
        assert httpx.Client.send is not before[0]
        assert httpx.AsyncClient.send is not before[1]
    finally:
        egress.unpatch_httpx_egress_guard()
    assert httpx.Client.send is before[0]
    assert httpx.AsyncClient.send is before[1]
