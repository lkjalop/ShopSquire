from __future__ import annotations

import os
from typing import Iterable, Tuple


class SecurityHeadersMiddleware:
    """ASGI middleware that applies baseline security headers."""

    def __init__(self, app):
        self.app = app
        self.enabled = str(os.getenv("SECURITY_HEADERS_ENABLED", "1")).lower() in ("1", "true", "yes")
        self.headers: Iterable[Tuple[bytes, bytes]] = self._build_headers()

    @staticmethod
    def _env(name: str, default: str) -> str:
        return str(os.getenv(name, default) or default)

    def _build_headers(self) -> list[Tuple[bytes, bytes]]:
        csp = self._env(
            "SECURITY_CSP",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'",
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

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                headers = list(message.get("headers", []))
                for hk, hv in self.headers:
                    if hk not in existing:
                        headers.append((hk, hv))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def secure_cookie_flags(*, oauth_flow: bool = False) -> dict:
    """Default cookie flags for secure session/auth cookies."""
    same_site = "None" if oauth_flow else "Lax"
    return {"secure": True, "httponly": True, "samesite": same_site}
