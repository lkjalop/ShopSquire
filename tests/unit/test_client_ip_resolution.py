from starlette.requests import Request

from src.app.security.client_ip import resolve_client_ip


def _request(peer: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 43210),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_untrusted_peer_cannot_spoof_forwarded_for(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")

    resolved = resolve_client_ip(_request("203.0.113.9", "198.51.100.4"))

    assert resolved.ip == "203.0.113.9"
    assert resolved.source == "peer"
    assert resolved.forwarded_ignored is True


def test_trusted_proxy_chain_is_walked_from_right_to_left(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8,192.0.2.0/24")

    resolved = resolve_client_ip(
        _request("10.20.0.4", "6.6.6.6, 198.51.100.24, 192.0.2.42")
    )

    assert resolved.ip == "198.51.100.24"
    assert resolved.source == "trusted_forwarded"
    assert resolved.trusted_proxy_hops == 2
    assert resolved.forwarded_ignored is False


def test_azure_style_append_defeats_leftmost_spoof(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")

    resolved = resolve_client_ip(
        _request("10.20.0.4", "1.2.3.4, 198.51.100.24")
    )

    assert resolved.ip == "198.51.100.24"
    assert resolved.source == "trusted_forwarded"


def test_malformed_forwarded_chain_fails_back_to_peer(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")

    resolved = resolve_client_ip(_request("10.20.0.4", "not-an-ip, also-bad"))

    assert resolved.ip == "10.20.0.4"
    assert resolved.source == "peer"
    assert resolved.malformed_forwarded is True

