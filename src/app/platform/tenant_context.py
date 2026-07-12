"""Active-tenant context (R10.2 step 2) — the ONE place request-tenant identity lives.

Mirrors store_profile's ContextVar pattern exactly (and is set by the SAME pure-ASGI
middleware, in the same task chain, so sync routes in the threadpool see it): the
X-Tenant-Id header → per-request ContextVar → 'default'. Data-layer helpers call
current_tenant_id() instead of growing a Header param on every endpoint — one authority,
no missed-endpoint split-brain (review-6 #5 class).

The header is already the app-wide tenant convention (P0.3: never client body, never
derived from uid). Single-tenant deployments never send it and resolve to 'default',
which is exactly what the draft_orders backfill stamped — zero behavior change.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_ACTIVE_TENANT_ID: "ContextVar[Optional[str]]" = ContextVar("active_tenant_id", default=None)

DEFAULT_TENANT = "default"


def set_active_tenant_id(tenant_id: Optional[str]):
    """Set the request's tenant (middleware only). Returns the reset token."""
    t = (str(tenant_id).strip() or None) if tenant_id is not None else None
    return _ACTIVE_TENANT_ID.set(t)


def reset_active_tenant_id(token) -> None:
    try:
        _ACTIVE_TENANT_ID.reset(token)
    except Exception:
        pass


def current_tenant_id() -> str:
    """The active tenant, never empty: request header → 'default'."""
    return _ACTIVE_TENANT_ID.get() or DEFAULT_TENANT
