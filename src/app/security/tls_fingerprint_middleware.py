from __future__ import annotations

import ipaddress
import os
import re
from typing import Any, Dict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


_JA3_RE = re.compile(r"^[a-f0-9]{32}$", re.IGNORECASE)
_JA4_RE = re.compile(r"^[a-z0-9_:-]{8,128}$", re.IGNORECASE)


def _enabled() -> bool:
    raw = os.getenv("TLS_FINGERPRINT_ENABLED")
    if raw is not None:
        return str(raw).strip().lower() in ("1", "true", "yes")
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env in ("prod", "production", "staging")


def _fail_closed_trust() -> bool:
    raw = os.getenv("TLS_FINGERPRINT_TRUST_FAIL_CLOSED")
    if raw is not None:
        return str(raw).strip().lower() in ("1", "true", "yes")
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env in ("prod", "production", "staging")


def _trusted_proxy_cidrs() -> list[str]:
    raw = str(
        os.getenv(
            "TLS_FINGERPRINT_TRUSTED_PROXY_CIDRS",
            os.getenv(
                "INTERNAL_MTLS_TRUSTED_PROXY_CIDRS",
                "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
            ),
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


def _norm_ja3(v: str | None) -> str:
    s = str(v or "").strip().lower()
    return s if _JA3_RE.match(s) else ""


def _norm_ja4(v: str | None) -> str:
    s = str(v or "").strip().lower()
    return s if _JA4_RE.match(s) else ""


def extract_tls_fingerprints_from_request(request: Request) -> Dict[str, Any]:
    state = getattr(request, "state", None)
    existing = getattr(state, "tls_fingerprints", None) if state is not None else None
    if isinstance(existing, dict):
        return dict(existing)

    source_ip = request.client.host if request.client else None
    trusted = _ip_in_cidrs(source_ip, _trusted_proxy_cidrs())
    out: Dict[str, Any] = {
        "source_ip": source_ip,
        "trusted_proxy_source": trusted,
        "ja3_hash": "",
        "ja4_hash": "",
    }
    if not trusted and _fail_closed_trust():
        return out

    h = request.headers
    out["ja3_hash"] = _norm_ja3(h.get("x-ja3-hash") or h.get("x-ja3"))
    out["ja4_hash"] = _norm_ja4(h.get("x-ja4-hash") or h.get("x-ja4"))
    return out


class TLSFingerprintMiddleware(BaseHTTPMiddleware):
    """Capture JA3/JA4 fingerprint headers from trusted proxy sources."""

    async def dispatch(self, request: Request, call_next):
        if _enabled():
            try:
                request.state.tls_fingerprints = extract_tls_fingerprints_from_request(request)
            except Exception:
                request.state.tls_fingerprints = {
                    "source_ip": request.client.host if request.client else None,
                    "trusted_proxy_source": False,
                    "ja3_hash": "",
                    "ja4_hash": "",
                }
        return await call_next(request)

