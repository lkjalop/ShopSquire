"""M06 — Zero-trust egress allowlist for outbound HTTP connections.

Enforces an ALLOWED_OUTBOUND_DOMAINS allowlist on all httpx calls made by the
application (including Celery tasks). Blocks connections to domains not in the
allowlist (e.g., dead-drop channels like Pastebin, raw.githubusercontent.com used
outside of the approved supply-chain monitoring context).

Configuration via environment variables:
    EGRESS_ALLOWLIST_ENABLED    — "1" (default) / "0" to disable
    ALLOWED_OUTBOUND_DOMAINS    — comma-separated domain whitelist (added to built-in defaults)
    EGRESS_ALLOWLIST_STRICT     — "0" (default, log+alert) / "1" (raise EgressBlockedError)
    EGRESS_ALLOWLIST_LOG_ONLY   — "1" means log violations but always allow (dev/test mode)

Built-in approved domains include common service endpoints that ShopSquire legitimately
contacts (LLM APIs, Vault, payment providers, etc.). Operators add their own via env.
"""
from __future__ import annotations

import logging
import os
import re
from typing import FrozenSet, Iterable, Optional
from urllib.parse import urlparse

_log = logging.getLogger("shopsquire.egress_allowlist")
_log.propagate = True

# ──────────────────────────────────────────────────────────────────────────────
# Default approved outbound domains
# (extend via ALLOWED_OUTBOUND_DOMAINS env var — comma-separated)
# ──────────────────────────────────────────────────────────────────────────────
_BUILTIN_ALLOWED_DOMAINS: FrozenSet[str] = frozenset(
    {
        # LLM providers
        "api.openai.com",
        "api.anthropic.com",
        "generativelanguage.googleapis.com",
        # Local Ollama (always allowed for local inference)
        "localhost",
        "127.0.0.1",
        "::1",
        # Starlette/FastAPI TestClient synthetic host; allow to avoid
        # self-blocking during in-process API contract/security tests.
        "testserver",
        # Internal service mesh (Docker / K8s)
        "redis",
        "postgres",
        "timescaledb",
        "celery",
        "ollama",
        # Payment providers
        "api.stripe.com",
        "hooks.stripe.com",
        "api.paypal.com",
        "api-m.paypal.com",
        "checkout.razorpay.com",
        # Vault / secrets
        "vault",
        "vault.service.consul",
        # Email
        "smtp.gmail.com",
        "smtp.office365.com",
        "graph.microsoft.com",
        "login.microsoftonline.com",
        "oauth2.googleapis.com",
        "www.googleapis.com",
        # Supply-chain monitoring (explicitly approved outbound)
        "services.nvd.nist.gov",
        "www.cisa.gov",
        "urlhaus.abuse.ch",
        "urlhaus-api.abuse.ch",
        "mb-api.abuse.ch",
        # Demo QR/document provider used by linked-artifact analysis fixtures
        "scanned.page",
        "www.scanned.page",
        "qr.scanned.page",
        "pypi.org",
        "pypi.python.org",
        "files.pythonhosted.org",
        # Telemetry / observability
        "ingest.sentry.io",
        "otlp.nr-data.net",
        # Shopper webhooks registered by merchant (generic webhook receivers)
        # These are validated per-request; the guard uses suffix matching.
    }
)

# Dead-drop and exfiltration channel blocklist (deny even if somehow allowlisted)
_KNOWN_DEAD_DROP_DOMAINS: FrozenSet[str] = frozenset(
    {
        "pastebin.com",
        "paste.ee",
        "hastebin.com",
        "ghostbin.com",
        "controlc.com",
        "dpaste.com",
        "paste.debian.net",
        "termbin.com",
        "sprunge.us",
        "ix.io",
        # C2 / collaboration dead-drops
        "discord.com",
        "discordapp.com",
        "cdn.discordapp.com",
        "hooks.slack.com",   # outbound Slack webhook — add explicitly when needed
        "api.notion.com",
        "api.telegram.org",
        # Public gist / raw file hosts (supply chain monitoring uses approved paths only)
        "gist.github.com",
        "raw.githubusercontent.com",
    }
)


class EgressBlockedError(PermissionError):
    """Raised when an outbound HTTP request to a blocked domain is attempted."""

    def __init__(self, url: str, reason: str = "domain_not_in_allowlist"):
        self.url = url
        self.reason = reason
        super().__init__(f"Outbound request blocked: {url!r} ({reason})")


class EgressDomainGuard:
    """Validates outbound URLs against the configured allowlist.

    Args:
        extra_allowed: additional domains to allow (merged with env var and built-ins).
        strict: if True raise EgressBlockedError on violations; if False only log+alert.
        log_only: override everything — log but always allow (useful in test/dev).
    """

    def __init__(
        self,
        *,
        extra_allowed: Iterable[str] | None = None,
        strict: bool | None = None,
        log_only: bool | None = None,
    ) -> None:
        env_domains = {
            d.strip().lower()
            for d in os.getenv("ALLOWED_OUTBOUND_DOMAINS", "").split(",")
            if d.strip()
        }
        extra = {d.strip().lower() for d in (extra_allowed or [])}
        self._allowed = _BUILTIN_ALLOWED_DOMAINS | env_domains | extra

        if strict is None:
            strict = os.getenv("EGRESS_ALLOWLIST_STRICT", "0").strip() in ("1", "true", "yes")
        self._strict = strict

        if log_only is None:
            log_only = os.getenv("EGRESS_ALLOWLIST_LOG_ONLY", "0").strip() in ("1", "true", "yes")
        self._log_only = log_only

        self._enabled = os.getenv("EGRESS_ALLOWLIST_ENABLED", "1").strip() not in ("0", "false", "no")

    def _extract_hostname(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            return (parsed.hostname or "").lower().strip()
        except Exception:
            return ""

    def _is_dead_drop(self, hostname: str) -> bool:
        return hostname in _KNOWN_DEAD_DROP_DOMAINS or any(
            hostname.endswith("." + d) for d in _KNOWN_DEAD_DROP_DOMAINS
        )

    def is_allowed(self, url: str) -> bool:
        """Return True if the URL hostname is on the allowlist."""
        if not self._enabled:
            return True
        hostname = self._extract_hostname(url)
        if not hostname:
            return True  # can't resolve — let the request proceed
        # Dead-drop check overrides allowlist
        if self._is_dead_drop(hostname):
            return False
        # Exact match
        if hostname in self._allowed:
            return True
        # Suffix match (e.g., "api.openai.com" matches "openai.com")
        for allowed in self._allowed:
            if hostname == allowed or hostname.endswith("." + allowed):
                return True
        return False

    def check(self, url: str) -> None:
        """Enforce allowlist. Logs and optionally raises EgressBlockedError."""
        if not self._enabled or self._log_only:
            if not self.is_allowed(url) and self._enabled:
                if _log.disabled:
                    _log.disabled = False
                _log.warning("EGRESS_VIOLATION (log-only): %s", url)
                self._emit_security_event(url, "log_only")
            return
        if not self.is_allowed(url):
            hostname = self._extract_hostname(url)
            reason = "dead_drop_channel" if self._is_dead_drop(hostname) else "domain_not_in_allowlist"
            if _log.disabled:
                _log.disabled = False
            _log.warning("EGRESS BLOCKED: %s (%s)", url, reason)
            self._emit_security_event(url, reason)
            if self._strict:
                raise EgressBlockedError(url, reason)

    def _emit_security_event(self, url: str, reason: str) -> None:
        try:
            from src.app.security.agent_events import (
                AgentInteractionType,
                ThreatCategory,
                log_agent_security_event,
            )
            log_agent_security_event(
                interaction_type=AgentInteractionType.tool_invocation,
                source="egress_allowlist",
                destination=url[:200],
                threat_category=ThreatCategory.dead_drop,
                severity="high",
                confidence=0.9,
                details={"blocked_url": url[:200], "reason": reason},
                requires_escalation=reason == "dead_drop_channel",
            )
        except Exception:
            pass  # Never let telemetry block request handling


# ──────────────────────────────────────────────────────────────────────────────
# httpx / requests monkey-patch
# ──────────────────────────────────────────────────────────────────────────────

_guard: EgressDomainGuard | None = None
_patched_httpx = False
_patched_requests = False
_orig_requests_send = None


def get_guard() -> EgressDomainGuard:
    global _guard
    if _guard is None:
        _guard = EgressDomainGuard()
    return _guard


def patch_httpx_egress_guard(guard: EgressDomainGuard | None = None) -> None:
    """Monkey-patch httpx.Client and httpx.AsyncClient to enforce egress allowlist.

    Idempotent — safe to call multiple times. The patch is applied globally for the
    process lifetime so that all outbound httpx calls (including those in third-party
    code) are subject to the allowlist.

    Call this once during application startup (e.g., in create_app()).
    """
    global _patched_httpx
    if _patched_httpx:
        return
    g = guard or get_guard()
    if not g._enabled:
        _log.info("Egress allowlist disabled (EGRESS_ALLOWLIST_ENABLED=0)")
        _patched_httpx = True
        return

    try:
        import httpx

        _orig_sync_send = httpx.Client.send
        _orig_async_send = httpx.AsyncClient.send

        def _patched_send(self_client, request, *args, **kwargs):
            g.check(str(request.url))
            return _orig_sync_send(self_client, request, *args, **kwargs)

        async def _patched_async_send(self_client, request, *args, **kwargs):
            g.check(str(request.url))
            return await _orig_async_send(self_client, request, *args, **kwargs)

        httpx.Client.send = _patched_send  # type: ignore[method-assign]
        httpx.AsyncClient.send = _patched_async_send  # type: ignore[method-assign]

        _patched_httpx = True
        _log.info(
            "Egress allowlist active — %d approved domains (strict=%s, log_only=%s)",
            len(g._allowed),
            g._strict,
            g._log_only,
        )
    except ImportError:
        _log.debug("httpx not installed; egress allowlist patch skipped")
        _patched_httpx = True


def patch_requests_egress_guard(guard: EgressDomainGuard | None = None) -> None:
    """Monkey-patch requests Session.send to enforce egress allowlist."""
    global _patched_requests, _orig_requests_send
    if _patched_requests:
        return
    g = guard or get_guard()
    if not g._enabled:
        _patched_requests = True
        return
    try:
        import requests

        _orig_requests_send = requests.sessions.Session.send

        def _patched_send(self_session, request, *args, **kwargs):
            try:
                g.check(str(getattr(request, "url", "") or ""))
            except Exception:
                raise
            return _orig_requests_send(self_session, request, *args, **kwargs)

        requests.sessions.Session.send = _patched_send  # type: ignore[method-assign]
        _patched_requests = True
        _log.info(
            "Egress allowlist active for requests â€” %d approved domains (strict=%s, log_only=%s)",
            len(g._allowed),
            g._strict,
            g._log_only,
        )
    except ImportError:
        _patched_requests = True


def patch_outbound_egress_guard(guard: EgressDomainGuard | None = None) -> None:
    """Patch both httpx and requests outbound clients."""
    patch_httpx_egress_guard(guard=guard)
    patch_requests_egress_guard(guard=guard)


def unpatch_httpx_egress_guard() -> None:
    """Remove monkey-patch (for testing only). Not thread-safe."""
    global _patched_httpx, _guard
    try:
        import httpx

        # Restore by reimporting originals from the module
        import importlib
        fresh = importlib.import_module("httpx")
        # Easiest reset: reload the module
        importlib.reload(fresh)
    except Exception:
        pass
    _patched_httpx = False
    _guard = None


def unpatch_requests_egress_guard() -> None:
    """Remove requests monkey-patch (for testing only)."""
    global _patched_requests, _orig_requests_send, _guard
    try:
        import requests

        if _orig_requests_send is not None:
            requests.sessions.Session.send = _orig_requests_send  # type: ignore[method-assign]
    except Exception:
        pass
    _orig_requests_send = None
    _patched_requests = False
    _guard = None


def unpatch_outbound_egress_guard() -> None:
    """Remove all outbound egress monkey-patches (for testing only)."""
    unpatch_httpx_egress_guard()
    unpatch_requests_egress_guard()


def egress_patch_state() -> dict:
    return {"httpx": bool(_patched_httpx), "requests": bool(_patched_requests)}
    _guard = None
