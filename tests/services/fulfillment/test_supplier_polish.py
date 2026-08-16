"""Caged LLM tone-polish: bounded + sanitized + JSON-only, returns None on any failure (deterministic
fallback in build_draft). Plus the flag-gated draft_and_record wiring (default OFF)."""
from __future__ import annotations

import os

from src.app.services.fulfillment import supplier_polish as sp


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


def _ok_post(safe_body):
    import json as _j
    return lambda url, json=None, timeout=None: _Resp(200, {"response": _j.dumps(
        {"subject": "Quote request", "body": safe_body})})


def test_polish_returns_safe_rewrite(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    out = sp.polish_supplier_draft(subject="s", body="b",
                                   _post=_ok_post("Hello, please share your quote. "
                                                  "This request does not constitute a purchase order."))
    assert out and out["subject"] == "Quote request" and "share your quote" in out["body"]


def test_polish_passes_a_timeout(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    seen = {}

    def _post(url, json=None, timeout=None):
        seen["timeout"] = timeout
        import json as _j
        return _Resp(200, {"response": _j.dumps({"subject": "s", "body": "ok. this request does not constitute a purchase order."})})
    sp.polish_supplier_draft(subject="s", body="b", timeout_s=5.0, _post=_post)
    assert seen["timeout"] == 5.0  # bounded — no silent hang


def test_polish_returns_none_on_failure(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")

    def _boom(url, json=None, timeout=None):
        raise RuntimeError("ollama down")
    assert sp.polish_supplier_draft(subject="s", body="b", _post=_boom) is None
    assert sp.polish_supplier_draft(subject="s", body="b",
                                    _post=lambda *a, **k: _Resp(500, {})) is None
    assert sp.polish_supplier_draft(subject="s", body="b",
                                    _post=lambda *a, **k: _Resp(200, {"response": "not json"})) is None


def test_polish_returns_none_without_ollama_url(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.setattr("src.app.services.llm_provider.OLLAMA_URL", "", raising=False)
    assert sp.polish_supplier_draft(subject="s", body="b", _post=_ok_post("x")) is None


def test_supplier_polish_flag_default_off():
    os.environ.pop("SUPPLIER_DRAFT_LLM_POLISH", None)
    from src.app.services.fulfillment.draft import _supplier_polish_enabled
    assert _supplier_polish_enabled() is False
