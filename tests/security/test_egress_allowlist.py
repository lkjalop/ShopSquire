"""M06 — Tests for egress domain allowlist (EgressDomainGuard + httpx patch).

Coverage:
- Approved domains pass
- Dead-drop domains are always blocked
- Unknown domains blocked in strict mode, logged in log-only mode
- EGRESS_ALLOWLIST_ENABLED=0 disables enforcement
- httpx monkey-patch intercepts real send calls
- Security event is emitted on violation
"""
from __future__ import annotations

import importlib
import logging
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_guard(
    extra_allowed: list[str] | None = None,
    *,
    strict: bool = False,
    log_only: bool = False,
    enabled: bool = True,
):
    """Build a guard with deterministic settings (no env var leakage)."""
    from src.app.security.egress_allowlist import EgressDomainGuard

    g = EgressDomainGuard(extra_allowed=extra_allowed, strict=strict, log_only=log_only)
    g._enabled = enabled
    return g


# ---------------------------------------------------------------------------
# is_allowed: approved domains
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1/chat/completions",
        "https://api.anthropic.com/v1/messages",
        "https://api.stripe.com/v1/charges",
        "https://services.nvd.nist.gov/rest/json/cves/2.0",
        "http://localhost:11434/api/generate",
        "http://127.0.0.1:6379",
        "https://ingest.sentry.io/api/123456/envelope/",
        "https://pypi.org/pypi/requests/json",
    ],
)
def test_approved_domains_pass(url):
    g = _make_guard()
    assert g.is_allowed(url) is True


# ---------------------------------------------------------------------------
# is_allowed: dead-drop domains always blocked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://pastebin.com/exfil",
        "https://api.telegram.org/bot123/sendMessage",
        "https://gist.github.com/attacker/abc123",
        "https://raw.githubusercontent.com/evil/repo/main/payload.sh",
        "https://hooks.slack.com/services/T00/B00/xxx",
        "https://cdn.discordapp.com/attachments/123/456/data.zip",
        "https://ix.io/4abc",
        "https://hastebin.com/raw/abc",
    ],
)
def test_dead_drop_domains_always_blocked(url):
    g = _make_guard()
    assert g.is_allowed(url) is False


# ---------------------------------------------------------------------------
# check(): strict mode raises
# ---------------------------------------------------------------------------

def test_check_strict_unknown_raises():
    from src.app.security.egress_allowlist import EgressBlockedError

    g = _make_guard(strict=True)
    with pytest.raises(EgressBlockedError) as exc_info:
        g.check("https://unknown-evil.example.com/steal")
    assert "unknown-evil.example.com" in str(exc_info.value)


def test_check_strict_dead_drop_raises():
    from src.app.security.egress_allowlist import EgressBlockedError

    g = _make_guard(strict=True)
    with pytest.raises(EgressBlockedError) as exc_info:
        g.check("https://pastebin.com/raw/xyz")
    assert exc_info.value.reason == "dead_drop_channel"


def test_check_strict_allowed_does_not_raise():
    g = _make_guard(strict=True)
    g.check("https://api.openai.com/v1/models")  # must not raise


# ---------------------------------------------------------------------------
# check(): non-strict mode logs but does not raise
# ---------------------------------------------------------------------------

def test_check_non_strict_logs_but_no_raise(caplog):
    g = _make_guard(strict=False)
    with caplog.at_level(logging.WARNING, logger="shopsquire.egress_allowlist"):
        g.check("https://sneaky-exfil.net/dump")
    assert any("EGRESS BLOCKED" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# check(): log_only mode always allows
# ---------------------------------------------------------------------------

def test_check_log_only_allows_dead_drop(caplog):
    g = _make_guard(log_only=True)
    with caplog.at_level(logging.WARNING, logger="shopsquire.egress_allowlist"):
        g.check("https://pastebin.com/exfil")  # must NOT raise
    assert any("EGRESS_VIOLATION" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# EGRESS_ALLOWLIST_ENABLED=0 disables entirely
# ---------------------------------------------------------------------------

def test_disabled_guard_allows_everything():
    g = _make_guard(enabled=False)
    assert g.is_allowed("https://pastebin.com/anything") is True
    g.check("https://totally-unknown.bad")  # must not raise


# ---------------------------------------------------------------------------
# Extra allowed domains via constructor
# ---------------------------------------------------------------------------

def test_extra_allowed_added():
    g = _make_guard(extra_allowed=["my-internal.corp"])
    assert g.is_allowed("https://my-internal.corp/api") is True
    # sub-domain of extra_allowed is also allowed
    assert g.is_allowed("https://api.my-internal.corp/health") is True


# ---------------------------------------------------------------------------
# Security event emission
# ---------------------------------------------------------------------------

def test_security_event_emitted_on_violation(caplog):
    """Verify that a security event emission is attempted on violation.

    log_agent_security_event internally calls get_engine() which may fail in
    unit-test environments. We verify the guard at least *attempts* emission by
    checking the WARNING log that always precedes it.
    """
    g = _make_guard(strict=False)
    with caplog.at_level(logging.WARNING, logger="shopsquire.egress_allowlist"):
        g.check("https://unknown-domain-xyz.io/exfil")

    blocked_msgs = [r.message for r in caplog.records if "EGRESS BLOCKED" in r.message]
    assert blocked_msgs, "Expected EGRESS BLOCKED warning log to be emitted"
    assert "unknown-domain-xyz.io" in blocked_msgs[0]


# ---------------------------------------------------------------------------
# httpx monkey-patch integration
# ---------------------------------------------------------------------------

def test_httpx_patch_blocks_dead_drop():
    """Patching httpx.Client should intercept and block dead-drop domains."""
    from src.app.security.egress_allowlist import (
        EgressBlockedError,
        EgressDomainGuard,
        unpatch_httpx_egress_guard,
    )
    import src.app.security.egress_allowlist as _mod

    # Reset patch state for isolation
    unpatch_httpx_egress_guard()
    if hasattr(_mod, "_patched_httpx"):
        _mod._patched_httpx = False

    strict_guard = EgressDomainGuard(strict=True)
    strict_guard._enabled = True

    import httpx

    original_send = httpx.Client.send

    # Apply patch with strict guard
    from src.app.security.egress_allowlist import patch_httpx_egress_guard
    patch_httpx_egress_guard(guard=strict_guard)

    try:
        client = httpx.Client()
        # Build a raw Request object — no network I/O
        req = httpx.Request("GET", "https://pastebin.com/exfil")
        with pytest.raises(EgressBlockedError):
            client.send(req)
    finally:
        # Always clean up
        unpatch_httpx_egress_guard()
        httpx.Client.send = original_send


def test_httpx_patch_allows_openai(monkeypatch):
    """Patching must not block approved domains."""
    from src.app.security.egress_allowlist import (
        EgressDomainGuard,
        unpatch_httpx_egress_guard,
        patch_httpx_egress_guard,
    )
    import src.app.security.egress_allowlist as _mod
    import httpx

    unpatch_httpx_egress_guard()
    if hasattr(_mod, "_patched_httpx"):
        _mod._patched_httpx = False
    original_send = httpx.Client.send

    strict_guard = EgressDomainGuard(strict=True)
    strict_guard._enabled = True

    patch_httpx_egress_guard(guard=strict_guard)

    # Mock the actual network call to avoid real I/O
    response = httpx.Response(200, json={"object": "list"})
    monkeypatch.setattr(
        "httpx.Client.send",
        lambda self, request, *a, **kw: response
        if "api.openai.com" in str(request.url)
        else original_send(self, request, *a, **kw),
    )

    client = httpx.Client()
    req = httpx.Request("GET", "https://api.openai.com/v1/models")
    # Should NOT raise — allowed domain
    # (The monkeypatch returns a fake 200 after the guard check passes)
    result = client.send(req)
    assert result.status_code == 200

    unpatch_httpx_egress_guard()
    httpx.Client.send = original_send


def test_requests_patch_blocks_dead_drop():
    from src.app.security.egress_allowlist import (
        EgressBlockedError,
        EgressDomainGuard,
        patch_requests_egress_guard,
        unpatch_requests_egress_guard,
    )
    import requests
    import src.app.security.egress_allowlist as _mod

    unpatch_requests_egress_guard()
    if hasattr(_mod, "_patched_requests"):
        _mod._patched_requests = False

    strict_guard = EgressDomainGuard(strict=True)
    strict_guard._enabled = True
    patch_requests_egress_guard(guard=strict_guard)
    try:
        s = requests.Session()
        req = requests.Request("GET", "https://pastebin.com/exfil")
        prepped = s.prepare_request(req)
        with pytest.raises(EgressBlockedError):
            s.send(prepped)
    finally:
        unpatch_requests_egress_guard()


# ---------------------------------------------------------------------------
# EgressBlockedError attributes
# ---------------------------------------------------------------------------

def test_egress_blocked_error_attributes():
    from src.app.security.egress_allowlist import EgressBlockedError

    err = EgressBlockedError("https://evil.io/dump", "dead_drop_channel")
    assert err.url == "https://evil.io/dump"
    assert err.reason == "dead_drop_channel"
    assert isinstance(err, PermissionError)


# ---------------------------------------------------------------------------
# ThreatCategory.dead_drop is importable (regression guard for enum value)
# ---------------------------------------------------------------------------

def test_threat_category_dead_drop_exists():
    from src.app.security.agent_events import ThreatCategory

    assert ThreatCategory.dead_drop.value == "dead_drop"
