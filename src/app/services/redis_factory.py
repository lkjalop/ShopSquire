"""Canonical Redis client factory.

Single point of construction for every raw `redis.from_url` / `redis.Redis(...)`
in the codebase — collapses 6 sites that previously diverged on:

  * socket / connect timeouts (some sites had no timeouts → silent hangs)
  * ACL username/password env lookup
  * `decode_responses` (some sites need bytes for streams/RQ, most need str)
  * TLS + ACL enforcement in non-dev environments

The factory NEVER raises: every failure path returns ``None`` so callers can
degrade gracefully (Redis is always best-effort in this codebase).
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

__all__ = ["create_redis_client"]


_DEV_ENVS = {"local", "dev", "development", "test", "testing"}


def create_redis_client(
    *,
    url: str | None = None,
    decode_responses: bool = True,
    async_client: bool = False,
    enforce_tls_acl: bool = False,
    connect_timeout: float | None = None,
    socket_timeout: float | None = None,
) -> Any | None:
    """Return a configured Redis client, or ``None`` on any failure.

    Args:
      url: Override the REDIS_URL env var.
      decode_responses: ``True`` → str responses (most callers); ``False`` →
        bytes (RQ workers, raw streams, sandbox xadd).
      async_client: Return a ``redis.asyncio`` client instead of sync.
      enforce_tls_acl: When True, require ``rediss://`` + REDIS_ACL_USERNAME/
        PASSWORD in non-dev environments (returns ``None`` if missing).
      connect_timeout / socket_timeout: Override the defaults from
        ``REDIS_CONNECT_TIMEOUT`` / ``REDIS_SOCKET_TIMEOUT`` env vars
        (defaults: 0.5s / 2.0s — fail-fast).
    """
    try:
        url = url or os.getenv("REDIS_URL") or "redis://localhost:6379/0"
        ct = (
            connect_timeout
            if connect_timeout is not None
            else float(os.getenv("REDIS_CONNECT_TIMEOUT", "0.5"))
        )
        ot = (
            socket_timeout
            if socket_timeout is not None
            else float(os.getenv("REDIS_SOCKET_TIMEOUT", "2.0"))
        )
        acl_user = (os.getenv("REDIS_ACL_USERNAME") or "").strip()
        acl_pass = (os.getenv("REDIS_ACL_PASSWORD") or "").strip()

        if enforce_tls_acl:
            env = (os.getenv("APP_ENV") or "local").strip().lower()
            if env not in _DEV_ENVS:
                parsed = urlparse(url)
                if (parsed.scheme or "").lower() != "rediss":
                    return None
                if not acl_user or not acl_pass:
                    return None

        kwargs: dict[str, Any] = {
            "decode_responses": decode_responses,
            "socket_connect_timeout": ct,
            "socket_timeout": ot,
        }
        if acl_user:
            kwargs["username"] = acl_user
        if acl_pass:
            kwargs["password"] = acl_pass

        if async_client:
            import redis.asyncio as redis_async  # type: ignore

            return redis_async.from_url(url, **kwargs)

        import redis as redis_sync  # type: ignore

        return redis_sync.from_url(url, **kwargs)
    except Exception:
        return None
