"""Pure-ASGI middleware that scopes the active StoreProfile (vertical) to each request.

WHY pure-ASGI (not BaseHTTPMiddleware): BaseHTTPMiddleware runs the endpoint in a SEPARATE anyio
task, which isolates a ContextVar set in dispatch() from the endpoint — the active vertical would
silently stay at the default (electronics), the exact silent-failure class we've been removing. A
pure-ASGI middleware sets the ContextVar in the SAME task chain before calling the inner app, and
anyio copies that live context into the threadpool that runs sync routes — so the route AND every
no-arg get_store_profile() see the request's vertical.

Resolution order (matches store_profile.active_profile_id): X-Store-Profile header →
STORE_PROFILE_ID env → electronics default. An unknown profile fails closed at load time in strict
mode (STORE_PROFILE_STRICT=1) — mis-routing a tenant to the wrong vertical is a compliance hazard.
"""
from __future__ import annotations

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id

_HEADER = b"x-store-profile"


class StoreProfileMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        pid = None
        try:
            for k, v in scope.get("headers") or []:
                if k == _HEADER:
                    pid = (v.decode("latin-1").strip() or None)
                    break
        except Exception:
            pid = None
        token = set_active_profile_id(pid)  # None → override cleared → env/default
        try:
            await self.app(scope, receive, send)
        finally:
            reset_active_profile_id(token)
