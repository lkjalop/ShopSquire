from __future__ import annotations

import asyncio

from src.app.routers import support_complaints as mod


def test_probe_redirect_chain_async_mode_returns_pending(monkeypatch):
    monkeypatch.setenv("QR_REDIRECT_PROBE_ENABLED", "1")
    monkeypatch.setenv("QR_REDIRECT_PROBE_MODE", "async")
    monkeypatch.setattr(mod, "_qr_redirect_cache_get", lambda _u: None)

    async def _fake_probe(_url: str, *, timeout_s: float = 1.5, max_hops: int = 3):
        return {"enabled": True, "checked": True, "chain": ["https://x"], "final_url": "https://x", "hops": 0}

    monkeypatch.setattr(mod, "_probe_redirect_chain_now", _fake_probe)
    out = asyncio.run(mod._probe_redirect_chain("https://x.example"))
    assert out["enabled"] is True
    assert out["checked"] is False
    assert out["pending"] is True


def test_probe_redirect_chain_sync_mode_runs_now(monkeypatch):
    monkeypatch.setenv("QR_REDIRECT_PROBE_ENABLED", "1")
    monkeypatch.setenv("QR_REDIRECT_PROBE_MODE", "sync")
    monkeypatch.setattr(mod, "_qr_redirect_cache_get", lambda _u: None)

    async def _fake_probe(_url: str, *, timeout_s: float = 1.5, max_hops: int = 3):
        return {"enabled": True, "checked": True, "chain": ["https://y"], "final_url": "https://y", "hops": 0}

    monkeypatch.setattr(mod, "_probe_redirect_chain_now", _fake_probe)
    out = asyncio.run(mod._probe_redirect_chain("https://y.example"))
    assert out["enabled"] is True
    assert out["checked"] is True
    assert out["cache_hit"] is False
