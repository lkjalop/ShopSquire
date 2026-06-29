from __future__ import annotations

import os
from typing import Iterable, Tuple


class SecurityHeadersMiddleware:
    """ASGI middleware that applies baseline security headers."""

    def __init__(self, app):
        self.app = app
        self.enabled = str(os.getenv("SECURITY_HEADERS_ENABLED", "1")).lower() in ("1", "true", "yes")
        self.headers: Iterable[Tuple[bytes, bytes]] = self._build_headers()
        # An API consumed by the browser SPA (incl. cross-origin in dev: :5173 → :8080) must allow
        # cross-origin resource reads, else CORP:same-origin blocks the fetch/stream with
        # ERR_BLOCKED_BY_RESPONSE.NotSameOrigin even when CORS allows it. CORS still gates WHO may read with
        # credentials; CORP only gates the no-cors block. Non-API responses keep the strict same-origin.
        self.corp_api = self._env("SECURITY_CORP_API", "cross-origin").encode("utf-8")

    @staticmethod
    def _env(name: str, default: str) -> str:
        return str(os.getenv(name, default) or default)

    def _build_headers(self) -> list[Tuple[bytes, bytes]]:
        # CRIT-07: Removed 'unsafe-inline' from script-src — use nonces for
        # any inline scripts.  Style 'unsafe-inline' retained until component
        # CSS-in-JS is migrated; track as TECH-DEBT-01.
        # frame-ancestors changed from 'self' → 'none' (clickjacking hardening).
        # Added report-uri so CSP violations reach our security event bus.
        csp = self._env(
            "SECURITY_CSP",
            (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob: https:; "
                "connect-src 'self' ws: wss:; "
                "media-src 'self' blob:; "
                "worker-src blob:; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none'; "
                "upgrade-insecure-requests; "
                "report-uri /api/v1/security/csp-report"
            ),
        )
        hsts_enabled = str(os.getenv("SECURITY_HSTS_ENABLED", "1")).lower() in ("1", "true", "yes")
        hsts = self._env("SECURITY_HSTS", "max-age=31536000; includeSubDomains")
        xcto = self._env("SECURITY_X_CONTENT_TYPE_OPTIONS", "nosniff")
        xfo = self._env("SECURITY_X_FRAME_OPTIONS", "DENY")
        refp = self._env("SECURITY_REFERRER_POLICY", "strict-origin-when-cross-origin")
        perms = self._env(
            "SECURITY_PERMISSIONS_POLICY",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        coop = self._env("SECURITY_COOP", "same-origin")
        coep = self._env("SECURITY_COEP", "unsafe-none")
        corp = self._env("SECURITY_CORP", "same-origin")

        out: list[Tuple[bytes, bytes]] = [
            (b"content-security-policy", csp.encode("utf-8")),
            (b"x-content-type-options", xcto.encode("utf-8")),
            (b"x-frame-options", xfo.encode("utf-8")),
            (b"referrer-policy", refp.encode("utf-8")),
            (b"permissions-policy", perms.encode("utf-8")),
            (b"cross-origin-opener-policy", coop.encode("utf-8")),
            (b"cross-origin-embedder-policy", coep.encode("utf-8")),
            (b"cross-origin-resource-policy", corp.encode("utf-8")),
        ]
        if hsts_enabled:
            out.append((b"strict-transport-security", hsts.encode("utf-8")))
        return out

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope.get("type") != "http":
            return await self.app(scope, receive, send)

        is_api = str(scope.get("path") or "").startswith("/api/")

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                headers = list(message.get("headers", []))
                for hk, hv in self.headers:
                    if hk not in existing:
                        # API responses are SPA-consumable cross-origin → relax only CORP for /api/*.
                        if is_api and hk == b"cross-origin-resource-policy":
                            headers.append((hk, self.corp_api))
                        else:
                            headers.append((hk, hv))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


# PCI DSS 6.4.3 — script inventory + justification for the payment page. Each script that runs on
# the checkout page is authorized and justified here; the CSP below enforces that ONLY these run.
PAYMENT_PAGE_SCRIPT_INVENTORY = [
    {
        "src": "inline (per-response nonce)",
        "purpose": "checkout bootstrap — read the cart snapshot, mount the Stripe Element, submit",
        "owner": "shopsquire",
        "integrity": "per-response CSP nonce",
    },
    {
        "src": "https://js.stripe.com/v3/",
        "purpose": "Stripe.js — PCI-compliant card tokenization; no PAN ever reaches our origin",
        "owner": "stripe",
        "integrity": "origin-pinned via CSP (Stripe.js cannot use SRI — Stripe rotates v3)",
    },
]


def payment_page_csp(nonce: str) -> str:
    """Strict Content-Security-Policy for a server-rendered payment page (PCI DSS 6.4.3 / 11.6.1
    anti-e-skimming). Authorizes EXACTLY what a Stripe checkout needs and nothing else:

      * script-src: 'self' + a per-response nonce (inline bootstrap) + js.stripe.com. No
        'unsafe-inline', no wildcards — an injected/skimmer script is blocked and reported.
      * frame-src/connect-src: scoped to Stripe Elements + the Stripe API.
      * report-uri: violations (i.e. unauthorized script attempts) hit the CSP-report sink so
        payment-page tampering is detected (11.6.1).

    Stripe.js deliberately has no SRI hash (Stripe rotates v3); its integrity control is
    official-origin pinning in script-src, documented in PAYMENT_PAGE_SCRIPT_INVENTORY."""
    n = str(nonce or "")
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{n}' https://js.stripe.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://api.stripe.com; "
        "frame-src https://js.stripe.com https://hooks.stripe.com; "
        "media-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; upgrade-insecure-requests; "
        "report-uri /api/v1/security/csp-report"
    )


def secure_cookie_flags(*, oauth_flow: bool = False) -> dict:
    """Default cookie flags for secure session/auth cookies."""
    same_site = "None" if oauth_flow else "Lax"
    return {"secure": True, "httponly": True, "samesite": same_site}
