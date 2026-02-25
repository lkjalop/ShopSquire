from __future__ import annotations

import hashlib
import os
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def _enabled() -> bool:
    return str(os.getenv("INTERNAL_MTLS_REQUIRED", "0")).lower() in ("1", "true", "yes")


def _paths() -> list[str]:
    raw = str(
        os.getenv(
            "INTERNAL_MTLS_PATH_PREFIXES",
            "/api/v1/orchestrator/events,/api/v1/webhooks,/api/v1/ingest",
        )
        or ""
    )
    out = [x.strip() for x in raw.split(",") if x.strip()]
    return out or ["/api/v1/orchestrator/events", "/api/v1/webhooks", "/api/v1/ingest"]


def _allowed_fingerprints() -> set[str]:
    raw = str(os.getenv("INTERNAL_MTLS_ALLOWED_FINGERPRINTS", "") or "")
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _normalize_fp(value: str) -> str:
    v = str(value or "").strip().lower()
    v = v.replace("sha256:", "").replace(":", "")
    return v


class InternalMTLSMiddleware(BaseHTTPMiddleware):
    """Enforce reverse-proxy validated mTLS headers on internal service paths."""

    def __init__(self, app, paths: Iterable[str] | None = None):
        super().__init__(app)
        self.paths = list(paths) if paths else _paths()

    async def dispatch(self, request: Request, call_next):
        if not _enabled():
            return await call_next(request)

        path = str(request.url.path or "")
        if not any(path.startswith(p) for p in self.paths):
            return await call_next(request)

        verify_hdr = str(request.headers.get("x-ssl-client-verify") or "").strip().upper()
        cert_hdr = str(request.headers.get("x-forwarded-client-cert") or request.headers.get("x-client-cert") or "").strip()
        fp_hdr = str(request.headers.get("x-ssl-client-fingerprint") or "").strip()

        if verify_hdr != "SUCCESS":
            return JSONResponse(status_code=401, content={"detail": "mtls_required"})
        if not cert_hdr and not fp_hdr:
            return JSONResponse(status_code=401, content={"detail": "mtls_client_cert_missing"})

        allowed = _allowed_fingerprints()
        if allowed:
            fp = _normalize_fp(fp_hdr)
            if not fp and cert_hdr:
                fp = hashlib.sha256(cert_hdr.encode("utf-8")).hexdigest().lower()
            if not fp or fp not in allowed:
                return JSONResponse(status_code=403, content={"detail": "mtls_client_fingerprint_not_allowed"})

        return await call_next(request)

