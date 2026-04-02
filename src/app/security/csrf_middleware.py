"""CRIT-08 — CSRF protection via double-submit cookie pattern.

Architecture
------------
1. Login issues two cookies:
   - ``ss_session`` — httpOnly, Secure, SameSite=Strict  (JWT, never readable by JS)
   - ``ss_csrf``    — Secure, SameSite=Strict, NOT httpOnly  (CSRF token, JS reads it)

2. Frontend reads ``ss_csrf`` cookie and sends it as the ``X-CSRF-Token`` header
   on every state-changing request (POST/PUT/PATCH/DELETE).

3. This middleware validates that header == cookie value using a timing-safe
   comparison.  A cross-origin attacker cannot read the cookie value because
   SameSite=Strict prevents the cookie being sent from a different origin,
   and the browser's same-origin policy prevents JS from reading a cookie
   set on a different origin.

Exempt paths
------------
Routes in ``CSRF_EXEMPT_PREFIXES`` are skipped (login, health, webhooks that
use their own HMAC, and the CSP report endpoint which has no auth).

Configuration
-------------
``CSRF_ENFORCEMENT``   — "enforce" (default in non-local) | "log" | "off"
``CSRF_COOKIE_NAME``   — default "ss_csrf"
``CSRF_HEADER_NAME``   — default "x-csrf-token"
``CSRF_MIN_SECRET_LEN``— default 32  (minimum accepted token length)

Framework alignment
-------------------
* PCI DSS 4.0 Req 6.2.4   — protect against CSRF on payment / account routes
* OWASP Top 10 A01:2021    — Broken Access Control (CSRF subtype)
* ISO 27001 A.8.9          — configuration management / secure defaults
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from typing import Callable, FrozenSet

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CSRF_COOKIE_NAME: str = os.getenv("CSRF_COOKIE_NAME", "ss_csrf")
CSRF_HEADER_NAME: str = os.getenv("CSRF_HEADER_NAME", "x-csrf-token").lower()
CSRF_MIN_LEN: int = max(16, int(os.getenv("CSRF_MIN_SECRET_LEN", "32") or 32))

# Methods that carry state — must be verified
_STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Paths that are exempt from CSRF checking.
# Webhooks use their own HMAC; auth/login issues the token; health + metrics
# are read-only; CSP report has no auth context.
CSRF_EXEMPT_PREFIXES: FrozenSet[str] = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/callback",
    "/api/v1/auth/refresh",
    "/api/v1/ingest/gmail/",
    "/api/v1/ingest/m365/",
    "/api/v1/webhooks/",
    "/api/v1/shopify/webhooks",
    "/api/v1/security/csp-report",
    "/health",
    "/healthz",
    "/metrics",
})


def _enforcement_mode() -> str:
    """Return 'enforce', 'log', or 'off'."""
    raw = str(os.getenv("CSRF_ENFORCEMENT", "") or "").strip().lower()
    if raw in ("enforce", "log", "off"):
        return raw
    # Default: enforce in non-local, log in local/dev/test
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return "enforce" if env not in ("local", "dev", "development", "test", "testing") else "log"


def _is_exempt(path: str) -> bool:
    for prefix in CSRF_EXEMPT_PREFIXES:
        if path == prefix or path.startswith(prefix):
            return True
    return False


def _safe_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison (constant time regardless of where mismatch occurs)."""
    if not a or not b:
        return False
    return hmac.compare_digest(
        hashlib.sha256(a.encode()).digest(),
        hashlib.sha256(b.encode()).digest(),
    )


class CSRFMiddleware:
    """ASGI middleware enforcing double-submit CSRF protection."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        method = request.method.upper()

        if method not in _STATE_CHANGING or _is_exempt(request.url.path):
            await self.app(scope, receive, send)
            return

        # API-key-authenticated requests are not vulnerable to CSRF:
        # browsers cannot send custom headers cross-origin without an explicit
        # CORS preflight approval, so the presence of x-api-key acts as its
        # own same-origin proof (analogous to Origin checking).
        if request.headers.get("x-api-key"):
            await self.app(scope, receive, send)
            return

        mode = _enforcement_mode()
        if mode == "off":
            await self.app(scope, receive, send)
            return

        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_token = request.headers.get(CSRF_HEADER_NAME, "")

        valid = (
            bool(cookie_token)
            and len(cookie_token) >= CSRF_MIN_LEN
            and _safe_compare(cookie_token, header_token)
        )

        if not valid:
            logger.warning(
                "csrf_validation_failed path=%s method=%s mode=%s "
                "cookie_present=%s header_present=%s",
                request.url.path,
                method,
                mode,
                bool(cookie_token),
                bool(header_token),
            )
            if mode == "enforce":
                response = JSONResponse(
                    {"detail": "csrf_validation_failed", "code": "CSRF_001"},
                    status_code=403,
                )
                await response(scope, receive, send)
                return
            # mode == "log" — let it through but record the miss

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Helper — generate a CSRF token and set cookie on the response
# ---------------------------------------------------------------------------

def generate_csrf_token() -> str:
    """Generate a cryptographically random CSRF token (64 hex chars)."""
    return secrets.token_hex(32)


def set_csrf_cookie(
    response_headers: MutableHeaders,
    token: str,
    *,
    secure: bool = True,
    same_site: str = "Strict",
    path: str = "/",
    domain: str | None = None,
) -> None:
    """Append a Set-Cookie header for the CSRF token.

    The cookie is intentionally NOT httpOnly so that JavaScript can read it
    and copy it into the X-CSRF-Token request header.
    """
    flags = [
        f"{CSRF_COOKIE_NAME}={token}",
        f"Path={path}",
        f"SameSite={same_site}",
    ]
    if secure:
        flags.append("Secure")
    if domain:
        flags.append(f"Domain={domain}")
    response_headers.append("set-cookie", "; ".join(flags))
