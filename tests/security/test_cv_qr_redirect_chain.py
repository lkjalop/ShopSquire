from __future__ import annotations

from src.app.services import cv_tier2_pipeline as mod


class _Resp:
    def __init__(self, status_code: int, location: str | None = None):
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}


def test_resolve_redirect_chain_bounded(monkeypatch):
    calls = []

    def _safe(_url: str):
        return None

    def _fake_get(url: str, allow_redirects: bool, timeout: float):
        calls.append((url, allow_redirects, timeout))
        if url == "https://a.example/x":
            return _Resp(302, "https://b.example/y")
        if url == "https://b.example/y":
            return _Resp(301, "/z")
        return _Resp(200)

    monkeypatch.setattr(mod, "ensure_safe_outbound_url", _safe)
    import requests

    monkeypatch.setattr(requests, "get", _fake_get)

    out = mod._resolve_redirect_chain("https://a.example/x", max_hops=5)
    assert out["final_url"] == "https://b.example/z"
    assert len(out["hops"]) == 3
    assert calls[0][1] is False
