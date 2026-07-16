"""P0-3 (test-anchored roadmap 2026-07-16): an explicit internal-service allowlist lets the local
model endpoint (e.g. Ollama at 127.0.0.1:11434 / localhost:11434) through the SSRF guard, which
otherwise blocks `localhost` always and `127.0.0.1` under prod defaults -> local vision silently
degrades. The allowlist must be SPECIFIC host:port entries, NOT a general private-network bypass,
and must NEVER be able to reach cloud-metadata endpoints.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("INTERNAL_SERVICE_ALLOWLIST", "APP_ENV", "EGRESS_ALLOWLIST_ONLY",
              "SSRF_ALLOW_PRIVATE", "SSRF_ALLOWLIST_HOSTS"):
        monkeypatch.delenv(k, raising=False)


def test_local_model_blocked_without_allowlist():
    from src.app.security import url_guard
    ok, reason = url_guard.validate_outbound_url("http://localhost:11434/api/tags")
    assert ok is False and reason == "blocked_host"   # the gap we are closing


def test_allowlist_permits_named_local_service(monkeypatch):
    from src.app.security import url_guard
    monkeypatch.setenv("INTERNAL_SERVICE_ALLOWLIST", "127.0.0.1:11434,localhost:11434")
    ok, reason = url_guard.validate_outbound_url("http://localhost:11434/api/tags")
    assert ok is True, reason
    ok, reason = url_guard.validate_outbound_url("http://127.0.0.1:11434/api/generate")
    assert ok is True, reason


def test_allowlist_works_even_in_prod(monkeypatch):
    from src.app.security import url_guard
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("INTERNAL_SERVICE_ALLOWLIST", "127.0.0.1:11434")
    ok, reason = url_guard.validate_outbound_url("http://127.0.0.1:11434/api/tags")
    assert ok is True, reason


def test_allowlist_cannot_reach_metadata(monkeypatch):
    from src.app.security import url_guard
    # Even a mis-configured allowlist naming the metadata endpoint must NOT reach it.
    monkeypatch.setenv("INTERNAL_SERVICE_ALLOWLIST", "169.254.169.254:80,169.254.169.254")
    ok, reason = url_guard.validate_outbound_url("http://169.254.169.254/latest/meta-data/")
    assert ok is False and reason == "blocked_host"


def test_allowlist_is_not_a_general_private_bypass(monkeypatch):
    from src.app.security import url_guard
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("INTERNAL_SERVICE_ALLOWLIST", "127.0.0.1:11434")
    # a DIFFERENT private host, not named in the allowlist, stays blocked
    ok, reason = url_guard.validate_outbound_url("http://10.0.0.5:8080/admin")
    assert ok is False
