"""Pure-ASGI middleware that scopes the active StoreProfile (vertical) to each request.

WHY pure-ASGI (not BaseHTTPMiddleware): BaseHTTPMiddleware runs the endpoint in a SEPARATE anyio
task, which isolates a ContextVar set in dispatch() from the endpoint — the active vertical would
silently stay at the default (electronics), the exact silent-failure class we've been removing. A
pure-ASGI middleware sets the ContextVar in the SAME task chain before calling the inner app, and
anyio copies that live context into the threadpool that runs sync routes — so the route AND every
no-arg get_store_profile() see the request's vertical.

Resolution order without a tenant registry: X-Store-Profile header -> STORE_PROFILE_ID env ->
electronics default. Once STORE_TENANT_REGISTRY_JSON/PATH is configured, X-Store-Profile is
validated against the request tenant's allowed profiles before request handlers run.
"""
from __future__ import annotations

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.platform.tenant_registry import resolve_store_profile_for_request

_HEADER = b"x-store-profile"
_TENANT_HEADER = b"x-tenant-id"


async def _deny(send, reason: str | None) -> None:
    body = (
        '{"detail":"store profile is not allowed for this tenant","reason":"'
        + str(reason or "denied")
        + '"}'
    ).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": 403,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class StoreProfileMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        pid = None
        tenant_id = None
        try:
            for k, v in scope.get("headers") or []:
                if k == _HEADER:
                    pid = (v.decode("latin-1").strip() or None)
                    continue
                if k == _TENANT_HEADER:
                    tenant_id = (v.decode("latin-1").strip() or None)
        except Exception:
            pid = None
            tenant_id = None
        resolved = resolve_store_profile_for_request(
            tenant_id=tenant_id,
            requested_profile_id=pid,
        )
        if not resolved.allowed:
            await _deny(send, resolved.reason)
            return
        pid = resolved.profile_id
        token = set_active_profile_id(pid)  # None → override cleared → env/default
        # R10.2: the SAME task chain also carries the active TENANT (X-Tenant-Id → 'default')
        # so data-layer helpers (cart/orders/privacy) read one authority via current_tenant_id()
        # instead of each endpoint growing a Header param (missed endpoint = split-brain).
        from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
        t_token = set_active_tenant_id(tenant_id)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_active_tenant_id(t_token)
            reset_active_profile_id(token)
