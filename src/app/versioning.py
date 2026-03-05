"""src/app/versioning.py — API versioning & deprecation support.

Provides:
  * ``API_VERSION`` — current stable version string ("v1")
  * ``DEPRECATED_VERSIONS`` — set of version strings that are deprecated
  * ``VersionDeprecationMiddleware`` — ASGI middleware that adds
    ``Deprecation`` / ``Sunset`` headers when a request hits a deprecated
    version prefix (e.g. ``/api/v0/...``).
  * ``deprecation_warning`` — decorator that marks an individual route as
    deprecated and injects headers into its response.

Design choices
--------------
* All current routes are under /api/v1/ (or no prefix — treated as v1).
* If a request arrives at /api/v0/... the middleware adds RFC-8594 headers
  and continues; we do NOT hard-break old clients immediately.
* v0 sunset date is configurable via the ``API_V0_SUNSET`` env var.
"""
from __future__ import annotations

import os
from datetime import datetime
from functools import wraps
from typing import Callable, Set

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Current stable API version
API_VERSION = "v1"

# Versions that are deprecated but still served
DEPRECATED_VERSIONS: Set[str] = {"v0"}

# RFC-8594 Sunset date for v0 (override via env; default is 6 months from now)
_DEFAULT_SUNSET = "Sat, 01 Nov 2025 00:00:00 GMT"
API_V0_SUNSET: str = os.getenv("API_V0_SUNSET", _DEFAULT_SUNSET)

# Link to migration guide
MIGRATION_GUIDE_URL = os.getenv(
    "API_MIGRATION_GUIDE_URL",
    "https://docs.shopsquire.io/api/migration/v0-to-v1",
)


class VersionDeprecationMiddleware(BaseHTTPMiddleware):
    """Add RFC-8594 Deprecation and Sunset headers when a deprecated API
    version prefix is detected in the request path.

    Example response headers added for ``/api/v0/anything``::

        Deprecation: true
        Sunset: Sat, 01 Nov 2025 00:00:00 GMT
        Link: <https://docs.shopsquire.io/api/migration/v0-to-v1>; rel="deprecation"
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable):
        response = await call_next(request)
        path = request.url.path
        for version in DEPRECATED_VERSIONS:
            if f"/api/{version}/" in path or path.startswith(f"/api/{version}"):
                response.headers["Deprecation"] = "true"
                response.headers["Sunset"] = API_V0_SUNSET
                response.headers["Link"] = (
                    f'<{MIGRATION_GUIDE_URL}>; rel="deprecation"'
                )
                break
        return response


def deprecation_warning(
    sunset: str = API_V0_SUNSET,
    migration_guide: str = MIGRATION_GUIDE_URL,
    message: str | None = None,
):
    """Decorator that marks a single route as deprecated.

    Injects ``Deprecation``, ``Sunset``, ``Link``, and optionally a
    ``Warning`` header into every response from the decorated endpoint.

    Usage::

        @router.get("/old-endpoint")
        @deprecation_warning(sunset="Sat, 01 Nov 2025 00:00:00 GMT")
        async def old_endpoint():
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            import inspect
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, Response):
                result.headers["Deprecation"] = "true"
                result.headers["Sunset"] = sunset
                result.headers["Link"] = f'<{migration_guide}>; rel="deprecation"'
                if message:
                    result.headers["Warning"] = f'299 - "{message}"'
            return result

        return wrapper
    return decorator


def get_api_version_info() -> dict:
    """Return current versioning metadata (used by /healthz and openapi tags)."""
    return {
        "current_version": API_VERSION,
        "deprecated_versions": sorted(DEPRECATED_VERSIONS),
        "sunset": {v: API_V0_SUNSET for v in DEPRECATED_VERSIONS},
        "migration_guide": MIGRATION_GUIDE_URL,
    }
