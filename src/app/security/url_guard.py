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
    # H01: Additional cloud metadata endpoints
    "metadata.google",
    "metadata.google.com",
    "100.100.100.200",           # Alibaba Cloud metadata
    "fd00:ec2::254",             # AWS IPv6 metadata
    "instance-data",             # Generic cloud metadata alias
}

_EGRESS_ALLOWLIST_CACHE: list[str] | None = None


def _load_egress_allowlist_file() -> set[str]:
    """Load egress allowlist from config/security/egress_allowlist.txt (one domain per line)."""
    global _EGRESS_ALLOWLIST_CACHE
    if _EGRESS_ALLOWLIST_CACHE is not None:
        return set(_EGRESS_ALLOWLIST_CACHE)
    path = os.getenv("EGRESS_ALLOWLIST_FILE", "config/security/egress_allowlist.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [
                line.strip().lower()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
        _EGRESS_ALLOWLIST_CACHE = lines
        return set(lines)
    except FileNotFoundError:
        _EGRESS_ALLOWLIST_CACHE = []
        return set()
    except Exception:
        _EGRESS_ALLOWLIST_CACHE = []
        return set()


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

    # Zero-trust egress mode: when EGRESS_ALLOWLIST_ONLY=1, ALL outbound
    # connections must match the allowlist — no fallthrough to open internet.
    egress_strict = str(os.getenv("EGRESS_ALLOWLIST_ONLY",
                                   "1" if _is_prod() else "0")).lower() in ("1", "true", "yes")

    allow_hosts = set(_csv_env("SSRF_ALLOWLIST_HOSTS"))
    # In strict mode, also load domain patterns from config file if present
    if egress_strict:
        allow_hosts.update(_load_egress_allowlist_file())

    if allow_hosts and host not in allow_hosts:
        # Check wildcard subdomains: *.example.com matches sub.example.com
        wildcard_ok = any(
            host.endswith("." + ah.lstrip("*."))
            for ah in allow_hosts
            if ah.startswith("*.")
        )
        if not wildcard_ok:
            reason = "egress_blocked_not_allowlisted" if egress_strict else "host_not_allowlisted"
            return False, reason

    # In strict mode with no allowlist configured, block everything outbound
    if egress_strict and not allow_hosts:
        import logging
        logging.getLogger("url_guard").error(
            "EGRESS_ALLOWLIST_ONLY=1 but no allowlist configured — blocking all outbound"
        )
        return False, "egress_no_allowlist_configured"

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
