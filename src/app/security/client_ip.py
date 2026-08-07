"""Trust-aware client IP resolution for reverse-proxy deployments."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from typing import Iterable

from starlette.requests import Request


@dataclass(frozen=True)
class ClientIPResolution:
    ip: str
    peer_ip: str
    source: str
    trusted_proxy_hops: int = 0
    forwarded_ignored: bool = False
    malformed_forwarded: bool = False


def _normalise_ip(value: str | None) -> str | None:
    candidate = str(value or "").strip().strip('"')
    if not candidate:
        return None
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        if candidate.count(":") == 1:
            host, port = candidate.rsplit(":", 1)
            if port.isdigit():
                try:
                    return str(ipaddress.ip_address(host))
                except ValueError:
                    return None
        return None


def _trusted_networks(raw: str | None = None) -> tuple[ipaddress._BaseNetwork, ...]:
    value = raw if raw is not None else os.getenv("TRUSTED_PROXY_CIDRS", "")
    networks: list[ipaddress._BaseNetwork] = []
    for item in (part.strip() for part in str(value or "").split(",")):
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted(ip: str, networks: Iterable[ipaddress._BaseNetwork]) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address.version == network.version and address in network for network in networks)


def resolve_client_ip(request: Request) -> ClientIPResolution:
    """Resolve a client address without trusting attacker-supplied leftmost values."""
    peer = _normalise_ip(request.client.host if request.client else None) or "unknown"
    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    networks = _trusted_networks()

    if not forwarded:
        result = ClientIPResolution(ip=peer, peer_ip=peer, source="peer")
        _record_resolution(result)
        return result
    if peer == "unknown" or not _is_trusted(peer, networks):
        result = ClientIPResolution(
            ip=peer, peer_ip=peer, source="peer", forwarded_ignored=True
        )
        _record_resolution(result)
        return result

    # Azure Container Apps appends its observed sender to the right. Walking
    # from right to left defeats a spoofed value supplied at the left edge.
    raw_chain = [part.strip() for part in forwarded.split(",")]
    if not raw_chain or len(raw_chain) > 32:
        result = ClientIPResolution(
            ip=peer, peer_ip=peer, source="peer", malformed_forwarded=True
        )
        _record_resolution(result)
        return result
    chain = [_normalise_ip(part) for part in raw_chain]
    if any(item is None for item in chain):
        result = ClientIPResolution(
            ip=peer, peer_ip=peer, source="peer", malformed_forwarded=True
        )
        _record_resolution(result)
        return result

    trusted_hops = 1
    parsed = [item for item in chain if item is not None]
    for candidate in reversed(parsed):
        if _is_trusted(candidate, networks):
            trusted_hops += 1
            continue
        result = ClientIPResolution(
            ip=candidate,
            peer_ip=peer,
            source="trusted_forwarded",
            trusted_proxy_hops=trusted_hops,
        )
        _record_resolution(result)
        return result

    result = ClientIPResolution(
        ip=parsed[0],
        peer_ip=peer,
        source="trusted_forwarded",
        trusted_proxy_hops=trusted_hops,
    )
    _record_resolution(result)
    return result


def _record_resolution(result: ClientIPResolution) -> None:
    try:
        from src.app.observability.metrics import record_client_ip_resolution

        outcome = (
            "malformed"
            if result.malformed_forwarded
            else "forwarded_ignored"
            if result.forwarded_ignored
            else "resolved"
        )
        record_client_ip_resolution(result.source, outcome)
    except Exception:
        pass


def client_ip(request: Request) -> str:
    return resolve_client_ip(request).ip
