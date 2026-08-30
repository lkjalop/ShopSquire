"""Governed direct retrieval of an allowlisted authoritative origin.

Discovery returns candidate URLs; it does not establish a claim.  This adapter
performs the distinct official-origin network operation and returns bounded raw
content plus a transport receipt.  Downstream parsers still have to emit typed
claims and the requirement compiler still owns authority.
"""
from __future__ import annotations

import hashlib
import asyncio
import ipaddress
import socket
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

import httpx

from src.app.services.research_certification_faults import active_research_fault
from src.app.security.egress_allowlist import scoped_egress_domains


_ALLOWED_CONTENT_TYPES = (
    "text/html", "text/plain", "application/json", "application/pdf",
    "application/xhtml+xml",
)


def _domain_allowed(host: str, allowlist: Iterable[str]) -> bool:
    normalized = str(host or "").strip().lower()
    return bool(normalized) and any(
        normalized == domain or normalized.endswith("." + domain)
        for raw in allowlist
        if (domain := str(raw or "").strip().lower())
    )


def _public_host(
    host: str,
    *,
    resolver: Callable[..., Any],
    allow_private: bool,
) -> bool:
    if allow_private:
        return True
    try:
        infos = resolver(host, None)
    except Exception:
        return False
    addresses = [row[4][0] for row in infos or [] if row and len(row) >= 5 and row[4]]
    if not addresses:
        return False
    for raw in addresses:
        try:
            address = ipaddress.ip_address(str(raw).split("%", 1)[0])
        except ValueError:
            return False
        if (
            address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast or address.is_unspecified
        ):
            return False
    return True


class GovernedOfficialOriginFetcher:
    """Fetch one exact official URL with fail-closed egress controls."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        resolver: Callable[..., Any] | None = None,
        allow_private: bool = False,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self._client = client
        self._resolver = resolver or socket.getaddrinfo
        self._allow_private = bool(allow_private)
        self._max_bytes = max(1024, min(int(max_bytes), 8 * 1024 * 1024))

    def fetch(
        self,
        url: str,
        *,
        allowlist: Iterable[str],
        timeout_s: float = 8.0,
        certification_run_id: str | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        parsed = urlparse(str(url or "").strip())
        host = str(parsed.hostname or "").lower()
        base_receipt = {
            "provider_capability": "OFFICIAL_ORIGIN_FETCH",
            "provider_id": "governed_http_origin",
            "provider_endpoint_host": host or None,
            "query_hash": hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:16],
            "certification_run_id": str(certification_run_id or "")[:120] or None,
            "started_at": started_at.isoformat(),
            "fixture": False,
            "network_execution": False,
            "external_call_dispatched": False,
            "cache_status": "miss",
            "billing_class": "free",
            "paid_calls": 0,
        }
        if parsed.scheme not in {"http", "https"} or not host:
            return self._failed(base_receipt, "origin_url_invalid")
        if parsed.username or parsed.password:
            return self._failed(base_receipt, "origin_credentials_forbidden")
        if not _domain_allowed(host, allowlist):
            return self._failed(base_receipt, "origin_domain_not_allowlisted")
        if not _public_host(
            host, resolver=self._resolver, allow_private=self._allow_private,
        ):
            return self._failed(base_receipt, "origin_host_not_public")
        if active_research_fault() == "publisher_timeout":
            return self._failed(
                {**base_receipt, "fixture": True},
                "certification_injected_publisher_timeout",
            )

        client = self._client or httpx.Client(
            timeout=timeout_s,
            follow_redirects=False,
            headers={"User-Agent": "ShopSquire-Official-Origin/1.0"},
        )
        owns_client = self._client is None
        try:
            # Crossing this line means an external call was dispatched even if
            # DNS, proxy negotiation, TLS, or the response later times out.
            dispatched_receipt = {
                **base_receipt,
                "network_execution": True,
                "external_call_dispatched": True,
            }
            # The adapter has already applied scheme, credential, public-IP and
            # exact source-policy checks. Permit only its governed allowlist for
            # this request so the global guard cannot drift from source policy.
            with scoped_egress_domains(allowlist):
                response = client.get(str(url), timeout=timeout_s)
            receipt = {
                **dispatched_receipt,
                "http_status": int(response.status_code),
            }
            if not 200 <= response.status_code < 300:
                return self._failed(receipt, "origin_http_status")
            content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].lower()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                return self._failed(receipt, "origin_content_type_not_allowed")
            body = bytes(response.content)
            if len(body) > self._max_bytes:
                return self._failed(receipt, "origin_body_too_large")
            completed_at = datetime.now(timezone.utc).isoformat()
            digest = hashlib.sha256(body).hexdigest()
            return {
                "status": "completed",
                "url": str(url)[:1000],
                "content": body,
                "content_type": content_type,
                # Raw origin content is untrusted input. It is not a requirement.
                "authority": "untrusted_origin_content_pending_compilation",
                "receipt": {
                    **receipt,
                    "completed_at": completed_at,
                    "observed_at": completed_at,
                    "response_body_hash": digest,
                    "response_bytes": len(body),
                    "execution_status": "completed",
                },
            }
        except Exception as exc:
            return self._failed(
                dispatched_receipt, f"origin_transport_error:{type(exc).__name__}",
            )
        finally:
            if owns_client:
                client.close()

    @staticmethod
    def _failed(receipt: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "status": "failed",
            "content": b"",
            "authority": "none",
            "error": reason,
            "receipt": {
                **receipt,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "execution_status": "failed",
                "error": reason,
            },
        }


class AsyncGovernedOfficialOriginFetcher(GovernedOfficialOriginFetcher):
    """Cancellation-aware official-origin transport for async request paths."""

    def __init__(self, *, client: httpx.AsyncClient | None = None, **kwargs: Any) -> None:
        super().__init__(client=None, **kwargs)
        self._async_client = client

    async def fetch_async(
        self, url: str, *, allowlist: Iterable[str], timeout_s: float = 8.0,
        certification_run_id: str | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        parsed = urlparse(str(url or "").strip())
        host = str(parsed.hostname or "").lower()
        base_receipt = {
            "provider_capability": "OFFICIAL_ORIGIN_FETCH",
            "provider_id": "governed_async_http_origin",
            "provider_endpoint_host": host or None,
            "query_hash": hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:16],
            "certification_run_id": str(certification_run_id or "")[:120] or None,
            "started_at": started_at.isoformat(), "fixture": False,
            "network_execution": False, "external_call_dispatched": False,
            "cache_status": "miss", "billing_class": "free", "paid_calls": 0,
        }
        if parsed.scheme not in {"http", "https"} or not host:
            return self._failed(base_receipt, "origin_url_invalid")
        if parsed.username or parsed.password:
            return self._failed(base_receipt, "origin_credentials_forbidden")
        if not _domain_allowed(host, allowlist):
            return self._failed(base_receipt, "origin_domain_not_allowlisted")
        if not _public_host(host, resolver=self._resolver, allow_private=self._allow_private):
            return self._failed(base_receipt, "origin_host_not_public")
        if active_research_fault() == "publisher_timeout":
            return self._failed(
                {**base_receipt, "fixture": True},
                "certification_injected_publisher_timeout",
            )
        client = self._async_client or httpx.AsyncClient(
            timeout=timeout_s, follow_redirects=False,
            headers={"User-Agent": "ShopSquire-Official-Origin/1.0"},
        )
        owns_client = self._async_client is None
        dispatched = {**base_receipt, "network_execution": True,
                      "external_call_dispatched": True}
        try:
            with scoped_egress_domains(allowlist):
                async with client.stream("GET", str(url), timeout=timeout_s) as response:
                    receipt = {**dispatched, "http_status": int(response.status_code)}
                    if not 200 <= response.status_code < 300:
                        return self._failed(receipt, "origin_http_status")
                    content_type = str(response.headers.get("content-type") or "").split(
                        ";", 1,
                    )[0].lower()
                    if content_type not in _ALLOWED_CONTENT_TYPES:
                        return self._failed(receipt, "origin_content_type_not_allowed")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_bytes:
                            return self._failed(receipt, "origin_body_too_large")
                        chunks.append(chunk)
            body = b"".join(chunks)
            completed_at = datetime.now(timezone.utc).isoformat()
            return {
                "status": "completed", "url": str(url)[:1000], "content": body,
                "content_type": content_type,
                "authority": "untrusted_origin_content_pending_compilation",
                "receipt": {
                    **receipt, "completed_at": completed_at, "observed_at": completed_at,
                    "response_body_hash": hashlib.sha256(body).hexdigest(),
                    "response_bytes": len(body), "execution_status": "completed",
                },
            }
        except asyncio.CancelledError:
            # Cancellation must reach the socket read; never relabel it as a
            # normal transport failure and continue work after buyer departure.
            raise
        except Exception as exc:
            return self._failed(dispatched, f"origin_transport_error:{type(exc).__name__}")
        finally:
            if owns_client:
                await client.aclose()


__all__ = ["AsyncGovernedOfficialOriginFetcher", "GovernedOfficialOriginFetcher"]
