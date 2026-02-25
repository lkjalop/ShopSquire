from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


_BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
}


def _is_prod() -> bool:
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env in ("prod", "production")


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = str(os.getenv(name, default) or "").strip()
    if not raw:
        return []
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def _is_blocked_ip(ip_text: str, *, allow_private: bool = False) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except Exception:
        return True
    # Always block metadata endpoint.
    if str(ip_text).strip() == "169.254.169.254":
        return True
    if allow_private:
        return bool(ip.is_multicast or ip.is_reserved or ip.is_unspecified)
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_outbound_url(url: str) -> tuple[bool, str]:
    """Validate an outbound URL to reduce SSRF risk.

    Returns:
      (ok, reason)
    """
    raw = str(url or "").strip()
    if not raw:
        return False, "empty_url"
    try:
        p = urlparse(raw)
    except Exception:
        return False, "parse_error"

    scheme = str(p.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, "invalid_scheme"
    if p.username or p.password:
        return False, "userinfo_not_allowed"
    host = str(p.hostname or "").strip().lower()
    if not host:
        return False, "missing_host"

    if host in _BLOCKED_HOSTS:
        return False, "blocked_host"

    allow_hosts = set(_csv_env("SSRF_ALLOWLIST_HOSTS"))
    if allow_hosts and host not in allow_hosts:
        return False, "host_not_allowlisted"

    deny_hosts = set(_csv_env("SSRF_DENYLIST_HOSTS"))
    if host in deny_hosts:
        return False, "host_denylisted"

    allow_private = str(os.getenv("SSRF_ALLOW_PRIVATE", "0" if _is_prod() else "1")).lower() in (
        "1",
        "true",
        "yes",
    )

    # Direct IP literals.
    try:
        ipaddress.ip_address(host)
        if _is_blocked_ip(host, allow_private=allow_private):
            return False, "blocked_ip_literal"
        return True, "ok"
    except Exception:
        pass

    # DNS-resolved IPs.
    try:
        infos = socket.getaddrinfo(host, None)
        addrs = [x[4][0] for x in infos if x and len(x) >= 5 and x[4]]
    except Exception:
        addrs = []

    block_unresolved = str(os.getenv("SSRF_BLOCK_UNRESOLVED", "1" if _is_prod() else "0")).lower() in (
        "1",
        "true",
        "yes",
    )
    if not addrs:
        return (False, "dns_unresolved") if block_unresolved else (True, "ok_unresolved")

    for ip_text in addrs:
        if _is_blocked_ip(ip_text, allow_private=allow_private):
            return False, "dns_resolved_to_blocked_ip"
    return True, "ok"


def ensure_safe_outbound_url(url: str) -> None:
    ok, reason = validate_outbound_url(url)
    if not ok:
        raise ValueError(f"unsafe_url:{reason}")
