from __future__ import annotations

import hashlib
import ipaddress
import os
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def _enabled() -> bool:
    raw = os.getenv("INTERNAL_MTLS_REQUIRED")
    if raw is not None:
        return str(raw).lower() in ("1", "true", "yes")
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env not in ("local", "dev", "development", "test", "testing")


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


def _fail_closed() -> bool:
    raw = os.getenv("INTERNAL_MTLS_FAIL_CLOSED")
    if raw is not None:
        return str(raw).lower() in ("1", "true", "yes")
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env in ("prod", "production", "staging")


def _trusted_proxy_cidrs() -> list[str]:
    raw = str(
        os.getenv(
            "INTERNAL_MTLS_TRUSTED_PROXY_CIDRS",
            "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        )
        or ""
    )
    return [x.strip() for x in raw.split(",") if x.strip()]


def _ip_in_cidrs(ip_text: str | None, cidrs: list[str]) -> bool:
    if not ip_text:
        return False
    try:
        ip = ipaddress.ip_address(str(ip_text).strip())
    except Exception:
        return False
    for c in cidrs:
        try:
            if ip in ipaddress.ip_network(c, strict=False):
                return True
        except Exception:
            continue
    return False


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

        # Fail-closed guard: only trust mTLS headers when request comes from a trusted ingress proxy.
        source_ip = request.client.host if request.client else None
        if _fail_closed() and not _ip_in_cidrs(source_ip, _trusted_proxy_cidrs()):
            return JSONResponse(status_code=403, content={"detail": "mtls_untrusted_proxy_source"})

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

