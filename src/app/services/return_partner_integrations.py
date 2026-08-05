"""Validated, provider-neutral boundary for return and repair partners.

The commerce core never accepts an endpoint from a buyer, attachment, or provider
response.  Adapters are configured by an operator and their replies remain
observations until a deterministic claim transition is separately authorized.
"""
from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import httpx


_MAX_RESPONSE_BYTES = 256 * 1024
_ALLOWED_STATUSES = {
    "accepted", "pending", "confirmed", "rejected", "unavailable", "cancelled",
}


@dataclass(frozen=True)
class PartnerEndpoint:
    provider_id: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    bearer_token: str | None = None
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class PartnerOutcome:
    status: str
    provider_id: str
    provider_reference: str | None = None
    tracking_number: str | None = None
    label_url: str | None = None
    detail: str | None = None
    authority: str = "provider_observation"


def _public_host(host: str, resolver: Callable[..., Any]) -> bool:
    try:
        rows = resolver(host, None)
    except Exception:
        return False
    addresses = [row[4][0] for row in rows if len(row) >= 5 and row[4]]
    if not addresses:
        return False
    for value in addresses:
        try:
            address = ipaddress.ip_address(str(value).split("%", 1)[0])
        except ValueError:
            return False
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return False
    return True


def validate_partner_endpoint(
    endpoint: PartnerEndpoint,
    *,
    resolver: Callable[..., Any] = socket.getaddrinfo,
) -> str:
    parsed = urlparse(endpoint.base_url)
    host = str(parsed.hostname or "").lower()
    allowed = {str(item).strip().lower() for item in endpoint.allowed_hosts if str(item).strip()}
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("partner_endpoint_must_be_https_without_userinfo")
    if host not in allowed:
        raise ValueError("partner_endpoint_host_not_allowlisted")
    if parsed.port not in (None, 443):
        raise ValueError("partner_endpoint_port_not_allowed")
    if not _public_host(host, resolver):
        raise ValueError("partner_endpoint_not_publicly_routable")
    return endpoint.base_url.rstrip("/")


def _bounded_partner_payload(data: Any, *, operation: str) -> PartnerOutcome:
    if not isinstance(data, Mapping):
        raise ValueError("partner_response_not_object")
    status = str(data.get("status") or "").strip().lower()
    if status not in _ALLOWED_STATUSES:
        raise ValueError("partner_response_status_invalid")
    reference = str(data.get("reference") or data.get("id") or "").strip()[:160] or None
    tracking = str(data.get("tracking_number") or "").strip()[:120] or None
    label_url = str(data.get("label_url") or "").strip()[:1000] or None
    if label_url:
        parsed = urlparse(label_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("partner_label_url_invalid")
    if operation == "return_label" and status == "confirmed" and not (tracking and label_url):
        raise ValueError("partner_label_response_incomplete")
    return PartnerOutcome(
        status=status,
        provider_id="",  # populated by the caller; provider cannot choose its identity
        provider_reference=reference,
        tracking_number=tracking,
        label_url=label_url,
        detail=str(data.get("detail") or "").strip()[:500] or None,
    )


class ValidatedReturnPartnerClient:
    """API10 boundary with fixed endpoints, bounded I/O, and typed failure states."""

    def __init__(
        self,
        endpoint: PartnerEndpoint,
        *,
        client: httpx.Client | None = None,
        resolver: Callable[..., Any] = socket.getaddrinfo,
    ) -> None:
        self._endpoint = endpoint
        self._base_url = validate_partner_endpoint(endpoint, resolver=resolver)
        self._client = client

    def request(
        self,
        *,
        operation: str,
        path: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
    ) -> PartnerOutcome:
        if operation not in {"return_label", "repair_booking", "repair_status"}:
            raise ValueError("unsupported_return_partner_operation")
        if not path.startswith("/") or "://" in path or ".." in path:
            raise ValueError("invalid_return_partner_path")
        if not 8 <= len(str(idempotency_key)) <= 128:
            raise ValueError("valid_partner_idempotency_key_required")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": str(idempotency_key),
        }
        if self._endpoint.bearer_token:
            headers["Authorization"] = f"Bearer {self._endpoint.bearer_token}"
        owns_client = self._client is None
        client = self._client or httpx.Client(
            timeout=self._endpoint.timeout_seconds,
            follow_redirects=False,
        )
        try:
            response = client.post(
                f"{self._base_url}{path}",
                headers=headers,
                json=dict(payload),
                timeout=self._endpoint.timeout_seconds,
            )
            if 300 <= response.status_code < 400:
                return PartnerOutcome(
                    status="invalid_response",
                    provider_id=self._endpoint.provider_id,
                    detail="partner_redirect_rejected",
                )
            if response.status_code == 429:
                return PartnerOutcome(
                    status="source_unavailable",
                    provider_id=self._endpoint.provider_id,
                    detail="partner_rate_limited",
                )
            if not 200 <= response.status_code < 300:
                return PartnerOutcome(
                    status="source_unavailable",
                    provider_id=self._endpoint.provider_id,
                    detail=f"partner_http_{response.status_code}",
                )
            if len(response.content) > _MAX_RESPONSE_BYTES:
                raise ValueError("partner_response_too_large")
            parsed = json.loads(response.content)
            outcome = _bounded_partner_payload(parsed, operation=operation)
            return PartnerOutcome(
                **{**outcome.__dict__, "provider_id": self._endpoint.provider_id}
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            return PartnerOutcome(
                status="source_unavailable",
                provider_id=self._endpoint.provider_id,
                detail="partner_transport_unavailable",
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            return PartnerOutcome(
                status="invalid_response",
                provider_id=self._endpoint.provider_id,
                detail=str(exc)[:500],
            )
        finally:
            if owns_client:
                client.close()
