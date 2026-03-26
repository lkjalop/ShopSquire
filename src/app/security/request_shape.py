from __future__ import annotations

import os
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def _is_non_dev_env() -> bool:
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env not in ("local", "dev", "development", "test", "testing")


def _max_request_bytes() -> int:
    raw = os.getenv("MAX_REQUEST_BODY_BYTES")
    if raw is not None:
        try:
            return max(0, int(raw))
        except Exception:
            return 0
    # Fail-safe default in non-dev env.
    return 1_048_576 if _is_non_dev_env() else 0


def _max_json_depth() -> int:
    try:
        return max(1, int(os.getenv("MAX_JSON_DEPTH", "24") or 24))
    except Exception:
        return 24


def _max_json_keys() -> int:
    try:
        return max(10, int(os.getenv("MAX_JSON_KEYS", "4000") or 4000))
    except Exception:
        return 4000


def _count_keys_and_depth(obj: Any, depth: int = 1) -> tuple[int, int]:
    if isinstance(obj, dict):
        keys = len(obj)
        max_d = depth
        for v in obj.values():
            k, d = _count_keys_and_depth(v, depth + 1)
            keys += k
            if d > max_d:
                max_d = d
        return keys, max_d
    if isinstance(obj, list):
        keys = 0
        max_d = depth
        for item in obj:
            k, d = _count_keys_and_depth(item, depth + 1)
            keys += k
            if d > max_d:
                max_d = d
        return keys, max_d
    return 0, depth


class GlobalRequestShapeMiddleware(BaseHTTPMiddleware):
    """Global request-size and JSON-shape caps to reduce API abuse blast radius."""

    async def dispatch(self, request: Request, call_next):
        max_bytes = _max_request_bytes()
        if max_bytes <= 0:
            return await call_next(request)

        ctype = str(request.headers.get("content-type") or "").lower()

        # Fast reject when Content-Length is clearly too large.
        cl_hdr = str(request.headers.get("content-length") or "").strip()
        if cl_hdr.isdigit() and int(cl_hdr) > max_bytes:
            return JSONResponse(status_code=413, content={"detail": "request_body_too_large", "max_bytes": max_bytes})

        # Do not eagerly buffer multipart streams. UploadFile handlers depend on
        # consuming the request body themselves, and reading it here can stall
        # file-upload routes under TestClient and production ASGI servers.
        if "multipart/form-data" in ctype:
            return await call_next(request)

        body = await request.body()
        if len(body) > max_bytes:
            return JSONResponse(status_code=413, content={"detail": "request_body_too_large", "max_bytes": max_bytes})

        # Enforce JSON shape caps for state-changing methods.
        method = str(request.method or "").upper()
        if method in ("POST", "PUT", "PATCH") and "application/json" in ctype and body:
            try:
                import json

                doc = json.loads(body)
                total_keys, max_depth = _count_keys_and_depth(doc)
                if total_keys > _max_json_keys():
                    return JSONResponse(status_code=413, content={"detail": "json_too_many_keys", "max_keys": _max_json_keys()})
                if max_depth > _max_json_depth():
                    return JSONResponse(status_code=413, content={"detail": "json_too_deep", "max_depth": _max_json_depth()})
            except Exception:
                # Leave parsing/validation errors to FastAPI request handling.
                pass

        return await call_next(request)
